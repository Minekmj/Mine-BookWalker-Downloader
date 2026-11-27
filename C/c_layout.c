#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "_common.h"

static PyObject *py_analyze_page_fast(PyObject *self, PyObject *args) {
    Py_buffer view;
    int w, h, sens_idx, small_illust, orig_w, orig_h;

    if (!PyArg_ParseTuple(args, "y*iiiiii", &view, &w, &h, &sens_idx, &small_illust, &orig_w, &orig_h)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (w < 10 || h < 10 || view.len < (Py_ssize_t)w * h * 3) {
        PyBuffer_Release(&view);
        return Py_BuildValue("(iiddddi)", 0, 0, 0.0, 0.0, 0.0, 0.0, 0);
    }

    if (orig_w <= 0) orig_w = w;
    if (orig_h <= 0) orig_h = h;

    int max_dim = imax(imax(w, h), imax(orig_w, orig_h));
    int step = max_dim > 700 ? (max_dim + 449) / 450 : 1;
    if (step < 1) step = 1;

    int sw = (w + step - 1) / step;
    int sh = (h + step - 1) / step;
    int s_orig_w = imax(1, orig_w / step);
    int s_orig_h = imax(1, orig_h / step);

    size_t total = (size_t)sw * sh;
    unsigned char *mask = (unsigned char *)calloc(total, 1);
    int stack_colink[768];
    int *col_ink = sw <= 768 ? stack_colink : (int *)malloc((size_t)sw * sizeof(int));
    int stack_xoff[768];
    int *x_off = sw <= 768 ? stack_xoff : (int *)malloc((size_t)sw * sizeof(int));

    if (!mask || !col_ink || !x_off) {
        free(mask);
        if (col_ink != stack_colink) free(col_ink);
        if (x_off != stack_xoff) free(x_off);
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }

    memset(col_ink, 0, (size_t)sw * sizeof(int));

    const unsigned char *data = (const unsigned char *)view.buf;
    long long total_samples = (long long)total;
    long long orig_samples = (long long)imax(1, s_orig_w * s_orig_h);
    long long ink_cnt = 0;
    long long color_cnt = 0;
    long long mid_cnt = 0;

    int oom = 0;
    int text_col_groups = 0;
    int max_color_blob = 0;
    int max_fg_blob = 0;
    int dominant_art_box = 0;
    int large_drawing_box = 0;
    int small_drawing_box = 0;

    double th_color, th_color_full, th_color_blob, th_blob, th_ink, th_mid;
    if (sens_idx == 0) {
        th_color = 0.05; th_color_full = 0.22; th_color_blob = 0.008; th_blob = 0.025; th_ink = 0.36; th_mid = 0.18;
    } else if (sens_idx == 2) {
        th_color = 0.015; th_color_full = 0.10; th_color_blob = 0.003; th_blob = 0.006; th_ink = 0.22; th_mid = 0.08;
    } else {
        th_color = 0.025; th_color_full = 0.16; th_color_blob = 0.0045; th_blob = 0.012; th_ink = 0.28; th_mid = 0.12;
    }

    int is_thin_text_strip = (sw < s_orig_w * 0.065) || (sh < s_orig_h * 0.045);
    int has_any_text = 0;
    int has_substantive_text = 0;
    int is_compact_graphic = 0;
    int is_illust = 0;
    int reason_code = 0;
    double ink_ratio = 0.0, color_ratio = 0.0, midtone_ratio = 0.0, largest_blob_ratio = 0.0;

    Py_BEGIN_ALLOW_THREADS
    for (int sx = 0; sx < sw; ++sx) {
        x_off[sx] = imin(w - 1, sx * step) * 3;
    }

    size_t row_stride = (size_t)w * 3;
    for (int sy = 0; sy < sh; ++sy) {
        int y = imin(h - 1, sy * step);
        const unsigned char *row = data + (size_t)y * row_stride;
        unsigned char *mrow = mask + (size_t)sy * sw;
        for (int sx = 0; sx < sw; ++sx) {
            const unsigned char *p = row + x_off[sx];
            int r = p[0], gv = p[1], b = p[2];
            if (((r - 231) | (gv - 231) | (b - 231)) < 0) {
                int g = calc_gray_rgb(r, gv, b);
                int is_c = (calc_color_diff_rgb(r, gv, b) > 24);
                int is_k = (g < 215) | is_c;
                if (is_k) {
                    mrow[sx] = (unsigned char)(1 | (is_c << 1));
                    ink_cnt++;
                    col_ink[sx]++;
                }
                if (is_c) {
                    color_cnt++;
                }
                if (g >= 55 && g <= 200) {
                    mid_cnt++;
                }
            }
        }
    }

    int col_th = imax(2, (int)(s_orig_h * 0.03));
    int max_narrow_w = imax(3, (int)(s_orig_w * 0.075));
    int in_grp = 0;
    int grp_start = 0;
    for (int sx = 0; sx < sw; ++sx) {
        if (col_ink[sx] >= col_th) {
            if (!in_grp) {
                in_grp = 1;
                grp_start = sx;
            }
        } else if (in_grp) {
            if (sx - grp_start <= max_narrow_w) text_col_groups++;
            in_grp = 0;
        }
    }
    if (in_grp && (sw - grp_start <= max_narrow_w)) {
        text_col_groups++;
    }

    uint32_t stack_q[8192];
    size_t q_cap = 8192;
    uint32_t *queue = stack_q;
    const int dx8[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
    const int dy8[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
    const double dw_40 = (double)s_orig_w * 0.40;
    const double dh_35 = (double)s_orig_h * 0.35;
    const double dw_30 = (double)s_orig_w * 0.30;
    const double dh_25 = (double)s_orig_h * 0.25;
    const double dw_065 = (double)s_orig_w * 0.065;
    const double dh_045 = (double)s_orig_h * 0.045;
    const double inv_orig = 1.0 / (double)orig_samples;

    if (ink_cnt > 0) {
        for (int sy = 0; sy < sh && !oom; ++sy) {
            unsigned char *mrow = mask + (size_t)sy * sw;
            for (int sx = 0; sx < sw; ++sx) {
                if (mrow[sx] & 1) {
                    size_t head = 0, tail = 0;
                    mrow[sx] &= (unsigned char)~1;
                    queue[tail++] = ((uint32_t)sy << 16) | (uint32_t)sx;
                    int minx = sw, maxx = 0, miny = sh, maxy = 0;
                    while (head < tail) {
                        uint32_t cur = queue[head++];
                        int cx = (int)(cur & 0xFFFFu);
                        int cy = (int)(cur >> 16);
                        if (cx < minx) minx = cx;
                        if (cx > maxx) maxx = cx;
                        if (cy < miny) miny = cy;
                        if (cy > maxy) maxy = cy;
                        if (cx > 0 && cx < sw - 1 && cy > 0 && cy < sh - 1) {
                            if (tail + 8 > q_cap) {
                                size_t new_cap = q_cap * 2;
                                if (new_cap < tail + 8) new_cap = tail + 8;
                                if (new_cap > total) new_cap = total;
                                uint32_t *nq;
                                if (queue == stack_q) {
                                    nq = (uint32_t *)malloc(new_cap * sizeof(uint32_t));
                                    if (nq) memcpy(nq, stack_q, tail * sizeof(uint32_t));
                                } else {
                                    nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
                                }
                                if (!nq) {
                                    oom = 1;
                                    break;
                                }
                                queue = nq;
                                q_cap = new_cap;
                            }
                            size_t base = (size_t)cy * sw + cx;
                            const int n_offs[8] = {-sw - 1, -sw, -sw + 1, -1, 1, sw - 1, sw, sw + 1};
                            const int n_dx[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
                            const int n_dy[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
                            for (int d = 0; d < 8; ++d) {
                                size_t nidx = (size_t)((ptrdiff_t)base + n_offs[d]);
                                if (mask[nidx] & 1) {
                                    mask[nidx] &= (unsigned char)~1;
                                    queue[tail++] = ((uint32_t)(cy + n_dy[d]) << 16) | (uint32_t)(cx + n_dx[d]);
                                }
                            }
                        } else {
                            for (int d = 0; d < 8; ++d) {
                                int nx = cx + dx8[d];
                                int ny = cy + dy8[d];
                                if (nx >= 0 && nx < sw && ny >= 0 && ny < sh) {
                                    size_t nidx = (size_t)ny * sw + nx;
                                    if (mask[nidx] & 1) {
                                        mask[nidx] &= (unsigned char)~1;
                                        if (tail >= q_cap) {
                                            size_t new_cap = q_cap * 2;
                                            if (new_cap > total) new_cap = total;
                                            uint32_t *nq;
                                            if (queue == stack_q) {
                                                nq = (uint32_t *)malloc(new_cap * sizeof(uint32_t));
                                                if (nq) memcpy(nq, stack_q, tail * sizeof(uint32_t));
                                            } else {
                                                nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
                                            }
                                            if (!nq) {
                                                oom = 1;
                                                break;
                                            }
                                            queue = nq;
                                            q_cap = new_cap;
                                        }
                                        queue[tail++] = ((uint32_t)ny << 16) | (uint32_t)nx;
                                    }
                                }
                            }
                        }
                        if (oom) break;
                    }
                    if (oom) break;
                    int blob_sz = (int)tail;
                    if (blob_sz > max_fg_blob) max_fg_blob = blob_sz;
                    int cw = maxx - minx + 1;
                    int ch = maxy - miny + 1;
                    double area_orig = (double)blob_sz * inv_orig;
                    if (cw >= dw_40 && ch >= dh_35 && area_orig >= 0.12) {
                        dominant_art_box = 1;
                    }
                    if (cw >= dw_30 && ch >= dh_25 && area_orig >= 0.08) {
                        large_drawing_box = 1;
                    }
                    if (small_illust && blob_sz >= 4 && cw >= dw_065 && ch >= dh_045) {
                        small_drawing_box = 1;
                    }
                }
            }
        }
    }

    ink_ratio = (double)ink_cnt / (double)total_samples;
    color_ratio = (double)color_cnt / (double)total_samples;
    midtone_ratio = (double)mid_cnt / (double)total_samples;
    largest_blob_ratio = (double)max_fg_blob / (double)total_samples;
    double max_blob_orig_ratio = (double)max_fg_blob * inv_orig;

    has_any_text = (text_col_groups >= 1);
    has_substantive_text = (text_col_groups >= 3);
    is_compact_graphic = (small_illust && !has_substantive_text && !is_thin_text_strip && sw <= s_orig_w * 0.42 && sh <= s_orig_h * 0.45 && sw >= s_orig_w * 0.09 && sh >= s_orig_h * 0.08 && ink_ratio >= 0.16);

    if (!oom) {
        if (is_thin_text_strip && color_ratio < 0.08 && max_blob_orig_ratio < 0.006 && !small_drawing_box) {
            is_illust = 0;
            reason_code = 0;
        } else if (is_compact_graphic && small_drawing_box && !has_substantive_text) {
            is_illust = 1;
            reason_code = 3;
        } else if (has_substantive_text && !dominant_art_box && color_ratio < 0.12) {
            is_illust = 0;
            reason_code = 0;
        } else if (has_any_text && !dominant_art_box && !large_drawing_box && max_blob_orig_ratio < 0.10 && color_ratio < 0.10 && !(ink_ratio >= 0.30 && midtone_ratio >= 0.12)) {
            is_illust = 0;
            reason_code = 0;
        } else if (color_ratio >= th_color_full) {
            is_illust = 1;
            reason_code = 1;
        } else {
            int color_branch = 0;
            if (color_cnt > 0 && color_ratio >= th_color && (!has_any_text || color_ratio >= 0.10)) {
                for (int sy = 0; sy < sh && !oom; ++sy) {
                    unsigned char *mrow = mask + (size_t)sy * sw;
                    for (int sx = 0; sx < sw; ++sx) {
                        if (mrow[sx] & 2) {
                            size_t head = 0, tail = 0;
                            mrow[sx] &= (unsigned char)~2;
                            queue[tail++] = ((uint32_t)sy << 16) | (uint32_t)sx;
                            while (head < tail) {
                                uint32_t cur = queue[head++];
                                int cx = (int)(cur & 0xFFFFu);
                                int cy = (int)(cur >> 16);
                                if (cx > 0 && cx < sw - 1 && cy > 0 && cy < sh - 1) {
                                    if (tail + 8 > q_cap) {
                                        size_t new_cap = q_cap * 2;
                                        if (new_cap < tail + 8) new_cap = tail + 8;
                                        if (new_cap > total) new_cap = total;
                                        uint32_t *nq;
                                        if (queue == stack_q) {
                                            nq = (uint32_t *)malloc(new_cap * sizeof(uint32_t));
                                            if (nq) memcpy(nq, stack_q, tail * sizeof(uint32_t));
                                        } else {
                                            nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
                                        }
                                        if (!nq) {
                                            oom = 1;
                                            break;
                                        }
                                        queue = nq;
                                        q_cap = new_cap;
                                    }
                                    size_t base = (size_t)cy * sw + cx;
                                    const int n_offs[8] = {-sw - 1, -sw, -sw + 1, -1, 1, sw - 1, sw, sw + 1};
                                    const int n_dx[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
                                    const int n_dy[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
                                    for (int d = 0; d < 8; ++d) {
                                        size_t nidx = (size_t)((ptrdiff_t)base + n_offs[d]);
                                        if (mask[nidx] & 2) {
                                            mask[nidx] &= (unsigned char)~2;
                                            queue[tail++] = ((uint32_t)(cy + n_dy[d]) << 16) | (uint32_t)(cx + n_dx[d]);
                                        }
                                    }
                                } else {
                                    for (int d = 0; d < 8; ++d) {
                                        int nx = cx + dx8[d];
                                        int ny = cy + dy8[d];
                                        if (nx >= 0 && nx < sw && ny >= 0 && ny < sh) {
                                            size_t nidx = (size_t)ny * sw + nx;
                                            if (mask[nidx] & 2) {
                                                mask[nidx] &= (unsigned char)~2;
                                                if (tail >= q_cap) {
                                                    size_t new_cap = q_cap * 2;
                                                    if (new_cap > total) new_cap = total;
                                                    uint32_t *nq;
                                                    if (queue == stack_q) {
                                                        nq = (uint32_t *)malloc(new_cap * sizeof(uint32_t));
                                                        if (nq) memcpy(nq, stack_q, tail * sizeof(uint32_t));
                                                    } else {
                                                        nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
                                                    }
                                                    if (!nq) {
                                                        oom = 1;
                                                        break;
                                                    }
                                                    queue = nq;
                                                    q_cap = new_cap;
                                                }
                                                queue[tail++] = ((uint32_t)ny << 16) | (uint32_t)nx;
                                            }
                                        }
                                    }
                                }
                                if (oom) break;
                            }
                            if (oom) break;
                            if ((int)tail > max_color_blob) {
                                max_color_blob = (int)tail;
                                if ((double)max_color_blob / (double)total_samples >= th_color_blob || (double)max_color_blob * inv_orig >= 0.005) {
                                    color_branch = 1;
                                    break;
                                }
                            }
                        }
                    }
                    if (color_branch) break;
                }
            }
            if (!oom) {
                if (color_branch) {
                    is_illust = 1;
                    reason_code = 1;
                } else if (dominant_art_box || large_drawing_box || (!has_any_text && !is_thin_text_strip && largest_blob_ratio >= th_blob && max_blob_orig_ratio >= 0.006)) {
                    is_illust = 1;
                    reason_code = 2;
                } else if (small_illust && !has_any_text && !is_thin_text_strip && small_drawing_box) {
                    is_illust = 1;
                    reason_code = 3;
                } else if (!has_substantive_text && !is_thin_text_strip && ink_ratio >= th_ink && midtone_ratio >= th_mid) {
                    is_illust = 1;
                    reason_code = 4;
                }
            }
        }
    }

    if (queue != stack_q) free(queue);
    if (col_ink != stack_colink) free(col_ink);
    if (x_off != stack_xoff) free(x_off);
    free(mask);
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);

    if (oom) {
        PyErr_NoMemory();
        return NULL;
    }

    return Py_BuildValue("(iiddddi)", is_illust, reason_code, ink_ratio, color_ratio, midtone_ratio, largest_blob_ratio, text_col_groups);
}

typedef struct {
    int ink;
    int col;
    int mid;
    int miny;
    int maxy;
} ColStat;

typedef struct {
    int x1;
    int x2;
    int y1;
    int y2;
    int is_illust;
    int is_text;
    int need_bfs;
    int ds_x1;
    int ds_x2;
    double seg_col_ratio;
} VSegment;

static PyObject *py_find_vertical_split(PyObject *self, PyObject *args) {
    Py_buffer view;
    int w, h, rtl;

    if (!PyArg_ParseTuple(args, "y*iii", &view, &w, &h, &rtl)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (w < 120 || h < 120 || view.len < (Py_ssize_t)w * h * 3) {
        PyBuffer_Release(&view);
        Py_RETURN_NONE;
    }

    const unsigned char *data = (const unsigned char *)view.buf;
    int step_y = h > 800 ? 3 : 1;
    int sample_h = (h + step_y - 1) / step_y;

    ColStat stack_cols[1024];
    ColStat *col_stats = w <= 1024 ? stack_cols : (ColStat *)malloc((size_t)w * sizeof(ColStat));
    if (!col_stats) {
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }

    int oom = 0;
    int found_split = 0;
    int ill_x1 = 0, ill_x2 = w, text_x1 = 0, text_x2 = 0;

    Py_BEGIN_ALLOW_THREADS
    for (int x = 0; x < w; ++x) {
        col_stats[x].ink = 0;
        col_stats[x].col = 0;
        col_stats[x].mid = 0;
        col_stats[x].miny = h;
        col_stats[x].maxy = -1;
    }

    const uint64_t mask_l = 0x7F7F7F7F7F7F7F7FULL;
    const uint64_t add_k = 0x1919191919191919ULL;
    const uint64_t mask_m = 0x8080808080808080ULL;
    size_t row_stride = (size_t)w * 3 * (size_t)step_y;
    const unsigned char *row = data;

    for (int y = 0; y < h; y += step_y, row += row_stride) {
        int x = 0;
        const unsigned char *p = row;
        for (; x + 8 <= w; x += 8, p += 24) {
            uint64_t w0, w1, w2;
            memcpy(&w0, p, 8);
            memcpy(&w1, p + 8, 8);
            memcpy(&w2, p + 16, 8);
            uint64_t a0 = w0 & ((w0 & mask_l) + add_k);
            uint64_t a1 = w1 & ((w1 & mask_l) + add_k);
            uint64_t a2 = w2 & ((w2 & mask_l) + add_k);
            if (((a0 & a1 & a2) & mask_m) == mask_m) {
                continue;
            }
            const unsigned char *q = p;
            for (int k = 0; k < 8; ++k, q += 3) {
                int r = q[0], gv = q[1], b = q[2];
                if (((r - 231) | (gv - 231) | (b - 231)) < 0) {
                    int g = calc_gray_rgb(r, gv, b);
                    int is_c = (calc_color_diff_rgb(r, gv, b) > 24);
                    ColStat *cs = &col_stats[x + k];
                    if (g < 210 || is_c) {
                        cs->ink++;
                        if (cs->miny == h) cs->miny = y;
                        cs->maxy = y;
                    }
                    if (is_c) cs->col++;
                    if (g >= 55 && g <= 200) cs->mid++;
                }
            }
        }
        for (; x < w; ++x, p += 3) {
            int r = p[0], gv = p[1], b = p[2];
            if (((r - 231) | (gv - 231) | (b - 231)) < 0) {
                int g = calc_gray_rgb(r, gv, b);
                int is_c = (calc_color_diff_rgb(r, gv, b) > 24);
                ColStat *cs = &col_stats[x];
                if (g < 210 || is_c) {
                    cs->ink++;
                    if (cs->miny == h) cs->miny = y;
                    cs->maxy = y;
                }
                if (is_c) cs->col++;
                if (g >= 55 && g <= 200) cs->mid++;
            }
        }
    }

    int gap_th = imax(1, sample_h / 250);
    int min_gap_w = imax(4, w / 250);
    VSegment stack_segs[64];
    int cap_segs = 64;
    VSegment *segs = stack_segs;
    int seg_cnt = 0;

    int in_seg = 0;
    int cur_x1 = 0;
    int gap_run = 0;

    for (int x = 0; x < w; ++x) {
        if (col_stats[x].ink > gap_th) {
            if (!in_seg) {
                in_seg = 1;
                cur_x1 = x;
            }
            gap_run = 0;
        } else if (in_seg) {
            gap_run++;
            if (gap_run >= min_gap_w) {
                int end_x = x - gap_run + 1;
                if (end_x - cur_x1 >= 3) {
                    if (seg_cnt >= cap_segs) {
                        int new_cap = cap_segs * 2;
                        VSegment *ns;
                        if (segs == stack_segs) {
                            ns = (VSegment *)malloc((size_t)new_cap * sizeof(VSegment));
                            if (ns) memcpy(ns, stack_segs, (size_t)seg_cnt * sizeof(VSegment));
                        } else {
                            ns = (VSegment *)realloc(segs, (size_t)new_cap * sizeof(VSegment));
                        }
                        if (!ns) {
                            oom = 1;
                            break;
                        }
                        segs = ns;
                        cap_segs = new_cap;
                    }
                    memset(&segs[seg_cnt], 0, sizeof(VSegment));
                    segs[seg_cnt].x1 = cur_x1;
                    segs[seg_cnt].x2 = end_x;
                    seg_cnt++;
                }
                in_seg = 0;
                gap_run = 0;
            }
        }
    }
    if (!oom && in_seg) {
        int end_x = w - gap_run;
        if (end_x - cur_x1 >= 3) {
            if (seg_cnt >= cap_segs) {
                int new_cap = cap_segs + 1;
                VSegment *ns;
                if (segs == stack_segs) {
                    ns = (VSegment *)malloc((size_t)new_cap * sizeof(VSegment));
                    if (ns) memcpy(ns, stack_segs, (size_t)seg_cnt * sizeof(VSegment));
                } else {
                    ns = (VSegment *)realloc(segs, (size_t)new_cap * sizeof(VSegment));
                }
                if (!ns) {
                    oom = 1;
                } else {
                    segs = ns;
                    cap_segs = new_cap;
                }
            }
            if (!oom) {
                memset(&segs[seg_cnt], 0, sizeof(VSegment));
                segs[seg_cnt].x1 = cur_x1;
                segs[seg_cnt].x2 = end_x;
                seg_cnt++;
            }
        }
    }

    if (!oom && seg_cnt >= 2) {
        int max_dim = imax(w, h);
        int ds = max_dim > 700 ? (max_dim + 349) / 350 : 1;
        if (ds < 1) ds = 1;
        int sw = (w + ds - 1) / ds;
        int sh = (h + ds - 1) / ds;

        int has_illust = 0;
        int can_illust_cnt = 0;
        int can_text_cnt = 0;
        int any_bfs = 0;

        for (int s = 0; s < seg_cnt; ++s) {
            int sx1 = segs[s].x1;
            int sx2 = segs[s].x2;
            int sy1 = h, sy2 = 0;
            long long s_ink = 0, s_col = 0, s_mid = 0;
            for (int x = sx1; x < sx2; ++x) {
                const ColStat *cs = &col_stats[x];
                s_ink += cs->ink;
                s_col += cs->col;
                s_mid += cs->mid;
                if (cs->miny < sy1) sy1 = cs->miny;
                if (cs->maxy > sy2) sy2 = cs->maxy;
            }
            sy2++;
            if (sy1 >= sy2) continue;
            segs[s].y1 = sy1;
            segs[s].y2 = sy2;

            int seg_w = sx2 - sx1;
            int seg_h = sy2 - sy1;
            double seg_sample_area = (double)seg_w * (double)imax(1, seg_h / step_y);
            double seg_ink_ratio = (double)s_ink / seg_sample_area;
            double seg_col_ratio = (double)s_col / seg_sample_area;
            double seg_mid_ratio = (double)s_mid / seg_sample_area;
            segs[s].seg_col_ratio = seg_col_ratio;
            segs[s].ds_x1 = imax(0, sx1 / ds);
            segs[s].ds_x2 = imin(sw, (sx2 + ds - 1) / ds);

            if (seg_w >= w * 0.25 && seg_h >= h * 0.25) {
                if (seg_col_ratio >= 0.02 || (seg_ink_ratio >= 0.22 && seg_mid_ratio >= 0.10)) {
                    segs[s].is_illust = 1;
                    has_illust = 1;
                } else {
                    segs[s].need_bfs = 1;
                    can_illust_cnt++;
                    any_bfs = 1;
                }
            }
            if (!segs[s].is_illust && !segs[s].need_bfs && seg_w >= imax(6, w / 120) && seg_w <= w * 0.18 && seg_h >= h * 0.05 && seg_col_ratio < 0.02) {
                segs[s].need_bfs = 2;
                can_text_cnt++;
                any_bfs = 1;
            }
        }

        if ((has_illust || can_illust_cnt > 0) && can_text_cnt > 0) {
            if (any_bfs) {
                size_t ds_total = (size_t)sw * sh;
                unsigned char *fg_mask = (unsigned char *)calloc(ds_total, 1);
                int stack_xoff[384];
                int *x_off = sw <= 384 ? stack_xoff : (int *)malloc((size_t)sw * sizeof(int));
                uint32_t stack_q[8192];
                size_t q_cap = 8192;
                uint32_t *queue = stack_q;

                if (!fg_mask || !x_off) {
                    oom = 1;
                } else {
                    for (int sx = 0; sx < sw; ++sx) {
                        x_off[sx] = imin(w - 1, sx * ds) * 3;
                    }
                    size_t w_stride = (size_t)w * 3;
                    for (int sy = 0; sy < sh; ++sy) {
                        int y = imin(h - 1, sy * ds);
                        const unsigned char *srow = data + (size_t)y * w_stride;
                        unsigned char *mrow = fg_mask + (size_t)sy * sw;
                        for (int sx = 0; sx < sw; ++sx) {
                            const unsigned char *p = srow + x_off[sx];
                            int r = p[0], gv = p[1], b = p[2];
                            if (((r - 231) | (gv - 231) | (b - 231)) < 0) {
                                if (calc_color_diff_rgb(r, gv, b) > 24 || r * 77 + gv * 150 + b * 29 < 53760) {
                                    mrow[sx] = 1;
                                }
                            }
                        }
                    }

                    const int dx8[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
                    const int dy8[8] = {-1, -1, -1, 0, 0, 1, 1, 1};

                    for (int s = 0; s < seg_cnt && !oom; ++s) {
                        if (segs[s].y1 >= segs[s].y2) continue;
                        int run_bfs = segs[s].need_bfs != 0;
                        int ds_x1 = segs[s].ds_x1;
                        int ds_x2 = segs[s].ds_x2;
                        if (!run_bfs) {
                            for (int k = s + 1; k < seg_cnt; ++k) {
                                if (segs[k].y1 < segs[k].y2 && segs[k].need_bfs != 0 && segs[k].ds_x1 < ds_x2) {
                                    run_bfs = 1;
                                    break;
                                }
                            }
                        }
                        if (!run_bfs) continue;

                        int max_blob = 0;
                        int max_blob_h = 0;
                        int comp_cnt = 0;

                        for (int sy = 0; sy < sh && !oom; ++sy) {
                            unsigned char *mrow = fg_mask + (size_t)sy * sw;
                            for (int sx = ds_x1; sx < ds_x2; ++sx) {
                                if (mrow[sx]) {
                                    size_t head = 0, tail = 0;
                                    mrow[sx] = 0;
                                    queue[tail++] = ((uint32_t)sy << 16) | (uint32_t)sx;
                                    int bminy = sh, bmaxy = 0;
                                    while (head < tail) {
                                        uint32_t cur = queue[head++];
                                        int cx = (int)(cur & 0xFFFFu);
                                        int cy = (int)(cur >> 16);
                                        if (cy < bminy) bminy = cy;
                                        if (cy > bmaxy) bmaxy = cy;
                                        if (cx > ds_x1 && cx < ds_x2 - 1 && cy > 0 && cy < sh - 1) {
                                            if (tail + 8 > q_cap) {
                                                size_t new_cap = q_cap * 2;
                                                if (new_cap < tail + 8) new_cap = tail + 8;
                                                if (new_cap > ds_total) new_cap = ds_total;
                                                uint32_t *nq;
                                                if (queue == stack_q) {
                                                    nq = (uint32_t *)malloc(new_cap * sizeof(uint32_t));
                                                    if (nq) memcpy(nq, stack_q, tail * sizeof(uint32_t));
                                                } else {
                                                    nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
                                                }
                                                if (!nq) {
                                                    oom = 1;
                                                    break;
                                                }
                                                queue = nq;
                                                q_cap = new_cap;
                                            }
                                            size_t base = (size_t)cy * sw + cx;
                                            const int n_offs[8] = {-sw - 1, -sw, -sw + 1, -1, 1, sw - 1, sw, sw + 1};
                                            const int n_dx[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
                                            const int n_dy[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
                                            for (int d = 0; d < 8; ++d) {
                                                size_t nidx = (size_t)((ptrdiff_t)base + n_offs[d]);
                                                if (fg_mask[nidx]) {
                                                    fg_mask[nidx] = 0;
                                                    queue[tail++] = ((uint32_t)(cy + n_dy[d]) << 16) | (uint32_t)(cx + n_dx[d]);
                                                }
                                            }
                                        } else {
                                            for (int d = 0; d < 8; ++d) {
                                                int nx = cx + dx8[d];
                                                int ny = cy + dy8[d];
                                                if (nx >= ds_x1 && nx < ds_x2 && ny >= 0 && ny < sh) {
                                                    size_t nidx = (size_t)ny * sw + nx;
                                                    if (fg_mask[nidx]) {
                                                        fg_mask[nidx] = 0;
                                                        if (tail >= q_cap) {
                                                            size_t new_cap = q_cap * 2;
                                                            if (new_cap > ds_total) new_cap = ds_total;
                                                            uint32_t *nq;
                                                            if (queue == stack_q) {
                                                                nq = (uint32_t *)malloc(new_cap * sizeof(uint32_t));
                                                                if (nq) memcpy(nq, stack_q, tail * sizeof(uint32_t));
                                                            } else {
                                                                nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
                                                            }
                                                            if (!nq) {
                                                                oom = 1;
                                                                break;
                                                            }
                                                            queue = nq;
                                                            q_cap = new_cap;
                                                        }
                                                        queue[tail++] = ((uint32_t)ny << 16) | (uint32_t)nx;
                                                    }
                                                }
                                            }
                                        }
                                        if (oom) break;
                                    }
                                    if (oom) break;
                                    int bh = bmaxy - bminy + 1;
                                    int blob_sz = (int)tail;
                                    if (blob_sz > max_blob) max_blob = blob_sz;
                                    if (bh > max_blob_h) max_blob_h = bh;
                                    if (blob_sz >= 2) comp_cnt++;
                                }
                            }
                        }
                        if (oom) break;

                        if (segs[s].need_bfs == 1) {
                            double max_blob_page_ratio = (double)max_blob / (double)ds_total;
                            double max_blob_h_ratio = (double)max_blob_h / (double)sh;
                            if (max_blob_h_ratio >= 0.15 || max_blob_page_ratio >= 0.015) {
                                segs[s].is_illust = 1;
                                has_illust = 1;
                            }
                        } else if (segs[s].need_bfs == 2) {
                            double max_blob_h_ratio = (double)max_blob_h / (double)sh;
                            if (max_blob_h_ratio <= 0.12 && comp_cnt >= 3) {
                                segs[s].is_text = 1;
                            }
                        }
                    }
                }
                if (queue != stack_q) free(queue);
                if (x_off != stack_xoff) free(x_off);
                free(fg_mask);
            }

            if (!oom && has_illust) {
                int first_ill = -1, last_ill = -1;
                for (int s = 0; s < seg_cnt; ++s) {
                    if (segs[s].is_illust) {
                        if (first_ill == -1) first_ill = s;
                        last_ill = s;
                    }
                }

                int left_text_cnt = 0;
                int left_non_text_art = 0;
                for (int s = 0; s < first_ill; ++s) {
                    if (segs[s].is_text) left_text_cnt++;
                    else if (segs[s].y2 - segs[s].y1 >= h * 0.20 && segs[s].x2 - segs[s].x1 >= w * 0.04) left_non_text_art = 1;
                }

                int right_text_cnt = 0;
                int right_non_text_art = 0;
                for (int s = last_ill + 1; s < seg_cnt; ++s) {
                    if (segs[s].is_text) right_text_cnt++;
                    else if (segs[s].y2 - segs[s].y1 >= h * 0.20 && segs[s].x2 - segs[s].x1 >= w * 0.04) right_non_text_art = 1;
                }

                if (left_text_cnt >= 1 && !left_non_text_art && right_text_cnt == 0) {
                    int last_txt_idx = -1;
                    for (int s = first_ill - 1; s >= 0; --s) {
                        if (segs[s].is_text) {
                            last_txt_idx = s;
                            break;
                        }
                    }
                    if (last_txt_idx >= 0 && last_txt_idx + 1 < seg_cnt) {
                        int gl = segs[last_txt_idx].x2;
                        int gr = segs[last_txt_idx + 1].x1;
                        int best_s = gl, best_e = gr, cur_s = -1, best_len = -1;
                        for (int gx = gl; gx <= gr && gx < w; ++gx) {
                            if (col_stats[gx].ink == 0) {
                                if (cur_s < 0) cur_s = gx;
                                if (gx - cur_s + 1 > best_len) {
                                    best_len = gx - cur_s + 1;
                                    best_s = cur_s;
                                    best_e = gx;
                                }
                            } else {
                                cur_s = -1;
                            }
                        }
                        int split_x = (best_s + best_e) / 2;
                        text_x1 = 0;
                        text_x2 = split_x;
                        ill_x1 = split_x;
                        ill_x2 = w;
                        found_split = 1;
                    }
                } else if (right_text_cnt >= 1 && !right_non_text_art && left_text_cnt == 0) {
                    int first_txt_idx = -1;
                    for (int s = last_ill + 1; s < seg_cnt; ++s) {
                        if (segs[s].is_text) {
                            first_txt_idx = s;
                            break;
                        }
                    }
                    if (first_txt_idx > 0) {
                        int gl = segs[first_txt_idx - 1].x2;
                        int gr = segs[first_txt_idx].x1;
                        int best_s = gl, best_e = gr, cur_s = -1, best_len = -1;
                        for (int gx = gl; gx <= gr && gx < w; ++gx) {
                            if (col_stats[gx].ink == 0) {
                                if (cur_s < 0) cur_s = gx;
                                if (gx - cur_s + 1 > best_len) {
                                    best_len = gx - cur_s + 1;
                                    best_s = cur_s;
                                    best_e = gx;
                                }
                            } else {
                                cur_s = -1;
                            }
                        }
                        int split_x = (best_s + best_e) / 2;
                        ill_x1 = 0;
                        ill_x2 = split_x;
                        text_x1 = split_x;
                        text_x2 = w;
                        found_split = 1;
                    }
                }
            }
        }
    }

    if (segs != stack_segs) free(segs);
    if (col_stats != stack_cols) free(col_stats);
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);

    if (oom) {
        PyErr_NoMemory();
        return NULL;
    }

    if (!found_split) {
        Py_RETURN_NONE;
    }

    return Py_BuildValue("((iiii)(iiii))", ill_x1, 0, ill_x2, h, text_x1, 0, text_x2, h);
}

static PyMethodDef LayoutMethods[] = {
    {"analyze_page_fast", py_analyze_page_fast, METH_VARARGS, NULL},
    {"find_vertical_split", py_find_vertical_split, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef c_layout_module = {
    PyModuleDef_HEAD_INIT,
    "c_layout",
    NULL,
    -1,
    LayoutMethods
};

PyMODINIT_FUNC PyInit_c_layout(void) {
    return PyModule_Create(&c_layout_module);
}