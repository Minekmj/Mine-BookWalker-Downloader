#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdint.h>
#include "_common.h"

static int hist_median(const int *hist, int total) {
    int half = total / 2;
    int acc = 0;
    for (int i = 0; i < 256; ++i) {
        acc += hist[i];
        if (acc > half) return i;
    }
    return 255;
}

static void morph_box_pass(unsigned char *mask, unsigned char *tmp, int w, int h, int radius, int is_erode, int *col_sum) {
    int ksize = radius * 2 + 1;
    int r_lim = imin(w - 1, radius);

    if (w >= 2 * radius + 2) {
        int mid_end = w - 2 - radius;
        for (int y = 0; y < h; ++y) {
            const unsigned char *srow = mask + (size_t)y * w;
            unsigned char *drow = tmp + (size_t)y * w;
            if (!is_erode) {
                if (!memchr(srow, 1, (size_t)w)) {
                    memset(drow, 0, (size_t)w);
                    continue;
                }
            } else {
                if (!memchr(srow, 0, (size_t)w)) {
                    memset(drow, 1, (size_t)w);
                    continue;
                }
            }
            int sum = 0;
            for (int x = 0; x <= radius; ++x) sum += srow[x];
            for (int x = 0; x < radius; ++x) {
                int cnt = x + radius + 1;
                drow[x] = is_erode ? (sum == cnt ? 1 : 0) : (sum > 0 ? 1 : 0);
                sum += srow[x + radius + 1];
            }
            for (int x = radius; x <= mid_end; ++x) {
                drow[x] = is_erode ? (sum == ksize ? 1 : 0) : (sum > 0 ? 1 : 0);
                sum += (int)srow[x + radius + 1] - (int)srow[x - radius];
            }
            for (int x = mid_end + 1; x < w; ++x) {
                int cnt = w - (x - radius);
                drow[x] = is_erode ? (sum == cnt ? 1 : 0) : (sum > 0 ? 1 : 0);
                sum -= srow[x - radius];
            }
        }
    } else {
        for (int y = 0; y < h; ++y) {
            const unsigned char *srow = mask + (size_t)y * w;
            unsigned char *drow = tmp + (size_t)y * w;
            int sum = 0;
            for (int x = 0; x <= r_lim; ++x) sum += srow[x];
            for (int x = 0; x < w; ++x) {
                int lx = imax(0, x - radius);
                int rx = imin(w - 1, x + radius);
                int cnt = rx - lx + 1;
                drow[x] = is_erode ? (sum == cnt ? 1 : 0) : (sum > 0 ? 1 : 0);
                int out_x = x - radius;
                int in_x = x + radius + 1;
                if (out_x >= 0) sum -= srow[out_x];
                if (in_x < w) sum += srow[in_x];
            }
        }
    }

    memset(col_sum, 0, (size_t)w * sizeof(int));
    int init_h = imin(h - 1, radius);
    for (int y = 0; y <= init_h; ++y) {
        const unsigned char *srow = tmp + (size_t)y * w;
        for (int x = 0; x < w; ++x) {
            col_sum[x] += srow[x];
        }
    }

    if (h >= 2 * radius + 2) {
        int mid_end_y = h - 2 - radius;
        for (int y = 0; y < radius; ++y) {
            int cnt = y + radius + 1;
            unsigned char *drow = mask + (size_t)y * w;
            const unsigned char *irow = tmp + (size_t)(y + radius + 1) * w;
            if (is_erode) {
                for (int x = 0; x < w; ++x) {
                    int cs = col_sum[x];
                    drow[x] = (cs == cnt) ? 1 : 0;
                    col_sum[x] = cs + irow[x];
                }
            } else {
                for (int x = 0; x < w; ++x) {
                    int cs = col_sum[x];
                    drow[x] = (cs > 0) ? 1 : 0;
                    col_sum[x] = cs + irow[x];
                }
            }
        }
        for (int y = radius; y <= mid_end_y; ++y) {
            unsigned char *drow = mask + (size_t)y * w;
            const unsigned char *orow = tmp + (size_t)(y - radius) * w;
            const unsigned char *irow = tmp + (size_t)(y + radius + 1) * w;
            if (is_erode) {
                for (int x = 0; x < w; ++x) {
                    int cs = col_sum[x];
                    drow[x] = (cs == ksize) ? 1 : 0;
                    col_sum[x] = cs - orow[x] + irow[x];
                }
            } else {
                for (int x = 0; x < w; ++x) {
                    int cs = col_sum[x];
                    drow[x] = (cs > 0) ? 1 : 0;
                    col_sum[x] = cs - orow[x] + irow[x];
                }
            }
        }
        for (int y = mid_end_y + 1; y < h; ++y) {
            int cnt = h - (y - radius);
            unsigned char *drow = mask + (size_t)y * w;
            const unsigned char *orow = tmp + (size_t)(y - radius) * w;
            if (is_erode) {
                for (int x = 0; x < w; ++x) {
                    int cs = col_sum[x];
                    drow[x] = (cs == cnt) ? 1 : 0;
                    col_sum[x] = cs - orow[x];
                }
            } else {
                for (int x = 0; x < w; ++x) {
                    int cs = col_sum[x];
                    drow[x] = (cs > 0) ? 1 : 0;
                    col_sum[x] = cs - orow[x];
                }
            }
        }
    } else {
        for (int y = 0; y < h; ++y) {
            int ty = imax(0, y - radius);
            int by = imin(h - 1, y + radius);
            int cnt = by - ty + 1;
            unsigned char *drow = mask + (size_t)y * w;
            if (is_erode) {
                for (int x = 0; x < w; ++x) drow[x] = (col_sum[x] == cnt) ? 1 : 0;
            } else {
                for (int x = 0; x < w; ++x) drow[x] = (col_sum[x] > 0) ? 1 : 0;
            }
            int out_y = y - radius;
            if (out_y >= 0) {
                const unsigned char *orow = tmp + (size_t)out_y * w;
                for (int x = 0; x < w; ++x) col_sum[x] -= orow[x];
            }
            int in_y = y + radius + 1;
            if (in_y < h) {
                const unsigned char *irow = tmp + (size_t)in_y * w;
                for (int x = 0; x < w; ++x) col_sum[x] += irow[x];
            }
        }
    }
}

typedef struct {
    int x1;
    int y1;
    int x2;
    int y2;
    int area;
} CompBox;

static PyObject *py_detect_illustration_bounds(PyObject *self, PyObject *args) {
    Py_buffer view;
    int width, height;
    double padding_ratio;

    if (!PyArg_ParseTuple(args, "y*iid", &view, &width, &height, &padding_ratio)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (width < 40 || height < 40 || view.len < (Py_ssize_t)width * height * 3) {
        PyBuffer_Release(&view);
        return Py_BuildValue("(iiii)", 0, 0, width, height);
    }

    int max_dim = imax(width, height);
    int step = max_dim > 750 ? (max_dim + 749) / 750 : 1;
    if (step < 1) step = 1;

    int w = imax(40, (width + step - 1) / step);
    int h = imax(40, (height + step - 1) / step);
    if (step == 1) {
        w = width;
        h = height;
    }

    size_t total = (size_t)w * h;
    unsigned char *mask = (unsigned char *)calloc(total, 1);
    unsigned char *tmp = (unsigned char *)malloc(total);
    int stack_xoff[768];
    int *x_off = w <= 768 ? stack_xoff : (int *)malloc((size_t)w * sizeof(int));
    int stack_cs[1024];
    int *col_sum = w <= 1024 ? stack_cs : (int *)malloc((size_t)w * sizeof(int));

    if (!mask || !tmp || !x_off || !col_sum) {
        free(mask);
        free(tmp);
        if (x_off != stack_xoff) free(x_off);
        if (col_sum != stack_cs) free(col_sum);
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }

    const unsigned char *data = (const unsigned char *)view.buf;
    int oom = 0;
    int res_x1 = 0, res_y1 = 0, res_x2 = width, res_y2 = height;

    Py_BEGIN_ALLOW_THREADS
    for (int sx = 0; sx < w; ++sx) {
        x_off[sx] = imin(width - 1, sx * step) * 3;
    }

    int patch_h = imax(2, (int)(h * 0.035));
    int patch_w = imax(2, (int)(w * 0.035));
    int hist_g[256] = {0};
    int hist_r[256] = {0};
    int hist_gr[256] = {0};
    int hist_b[256] = {0};
    int border_cnt = 0;
    size_t row_stride = (size_t)width * 3;

    for (int py = 0; py < patch_h; ++py) {
        int sys[2] = {py, h - patch_h + py};
        for (int yi = 0; yi < 2; ++yi) {
            int y = imin(height - 1, sys[yi] * step);
            const unsigned char *src_row = data + (size_t)y * row_stride;
            for (int px = 0; px < patch_w; ++px) {
                int sxs[2] = {px, w - patch_w + px};
                for (int xi = 0; xi < 2; ++xi) {
                    const unsigned char *p = src_row + x_off[sxs[xi]];
                    int r = p[0], g = p[1], b = p[2];
                    hist_g[calc_gray_rgb(r, g, b)]++;
                    hist_r[r]++;
                    hist_gr[g]++;
                    hist_b[b]++;
                    border_cnt++;
                }
            }
        }
    }

    int bg_gray = hist_median(hist_g, border_cnt);
    if (bg_gray >= 205) {
        int th = imax(170, imin(248, bg_gray - 11));
        int th256 = th << 8;
        int skip_th = imax(th, 222);
        for (int sy = 0; sy < h; ++sy) {
            int y = imin(height - 1, sy * step);
            const unsigned char *src_row = data + (size_t)y * row_stride;
            unsigned char *mrow = mask + (size_t)sy * w;
            for (int sx = 0; sx < w; ++sx) {
                const unsigned char *p = src_row + x_off[sx];
                int r = p[0], g = p[1], b = p[2];
                if (((r - skip_th) | (g - skip_th) | (b - skip_th)) < 0) {
                    if (r * 77 + g * 150 + b * 29 < th256 || is_hsv_vivid_rgb(r, g, b)) {
                        mrow[sx] = 1;
                    }
                }
            }
        }
    } else {
        int bg_r = hist_median(hist_r, border_cnt);
        int bg_gr = hist_median(hist_gr, border_cnt);
        int bg_b = hist_median(hist_b, border_cnt);
        int off_r = 22 - bg_r;
        int off_g = 22 - bg_gr;
        int off_b = 22 - bg_b;
        for (int sy = 0; sy < h; ++sy) {
            int y = imin(height - 1, sy * step);
            const unsigned char *src_row = data + (size_t)y * row_stride;
            unsigned char *mrow = mask + (size_t)sy * w;
            for (int sx = 0; sx < w; ++sx) {
                const unsigned char *p = src_row + x_off[sx];
                unsigned int dr = (unsigned int)((int)p[0] + off_r);
                unsigned int dg = (unsigned int)((int)p[1] + off_g);
                unsigned int db = (unsigned int)((int)p[2] + off_b);
                if ((dr > 44u) | (dg > 44u) | (db > 44u)) {
                    mrow[sx] = 1;
                }
            }
        }
    }

    if (x_off != stack_xoff) free(x_off);

    int ksize = imax(3, imin(13, (imin(w, h) / 100) | 1));
    int radius2 = (ksize / 2) * 2;
    morph_box_pass(mask, tmp, w, h, radius2, 0, col_sum);
    morph_box_pass(mask, tmp, w, h, radius2, 1, col_sum);

    free(tmp);
    if (col_sum != stack_cs) free(col_sum);

    uint32_t stack_q[8192];
    size_t q_cap = 8192;
    uint32_t *queue = stack_q;
    CompBox stack_boxes[128];
    int cap_boxes = 128;
    int num_boxes = 0;
    CompBox *boxes = stack_boxes;

    int min_area = imax(12, (int)((double)total * 0.000035));
    const int dx8[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
    const int dy8[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
    int dominant_area = 0;
    double w_035 = (double)w * 0.035;
    double h_035 = (double)h * 0.035;
    double w_004 = (double)w * 0.004;
    double h_012 = (double)h * 0.012;
    double w_015 = (double)w * 0.015;
    double h_025 = (double)h * 0.25;
    double h_015 = (double)h * 0.015;
    double w_025 = (double)w * 0.25;

    for (int sy = 0; sy < h && !oom; ++sy) {
        unsigned char *mrow = mask + (size_t)sy * w;
        for (int sx = 0; sx < w; ++sx) {
            if (mrow[sx]) {
                size_t head = 0, tail = 0;
                mrow[sx] = 0;
                queue[tail++] = ((uint32_t)sy << 16) | (uint32_t)sx;
                int minx = w, maxx = 0, miny = h, maxy = 0;
                while (head < tail) {
                    uint32_t cur = queue[head++];
                    int cx = (int)(cur & 0xFFFFu);
                    int cy = (int)(cur >> 16);
                    if (cx < minx) minx = cx;
                    if (cx > maxx) maxx = cx;
                    if (cy < miny) miny = cy;
                    if (cy > maxy) maxy = cy;
                    if (cx > 0 && cx < w - 1 && cy > 0 && cy < h - 1) {
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
                        size_t base = (size_t)cy * w + cx;
                        const int n_offs[8] = {-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1};
                        const int n_dx[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
                        const int n_dy[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
                        for (int d = 0; d < 8; ++d) {
                            size_t nidx = (size_t)((ptrdiff_t)base + n_offs[d]);
                            if (mask[nidx]) {
                                mask[nidx] = 0;
                                queue[tail++] = ((uint32_t)(cy + n_dy[d]) << 16) | (uint32_t)(cx + n_dx[d]);
                            }
                        }
                    } else {
                        for (int d = 0; d < 8; ++d) {
                            int nx = cx + dx8[d];
                            int ny = cy + dy8[d];
                            if (nx >= 0 && nx < w && ny >= 0 && ny < h) {
                                size_t nidx = (size_t)ny * w + nx;
                                if (mask[nidx]) {
                                    mask[nidx] = 0;
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
                int bw = maxx - minx + 1;
                int bh = maxy - miny + 1;
                int area = (int)tail;
                if (area < min_area && !(bw >= w_035 && bh >= h_035)) continue;
                if (bw < w_004 && bh < h_012) continue;
                if ((minx == 0 || maxx + 1 >= w) && bw <= w_015 && bh >= h_025) continue;
                if ((miny == 0 || maxy + 1 >= h) && bh <= h_015 && bw >= w_025) continue;
                if (area > dominant_area) dominant_area = area;
                if (num_boxes >= cap_boxes) {
                    int new_cap = cap_boxes * 2;
                    CompBox *nb;
                    if (boxes == stack_boxes) {
                        nb = (CompBox *)malloc((size_t)new_cap * sizeof(CompBox));
                        if (nb) memcpy(nb, stack_boxes, (size_t)num_boxes * sizeof(CompBox));
                    } else {
                        nb = (CompBox *)realloc(boxes, (size_t)new_cap * sizeof(CompBox));
                    }
                    if (!nb) break;
                    boxes = nb;
                    cap_boxes = new_cap;
                }
                boxes[num_boxes].x1 = minx;
                boxes[num_boxes].y1 = miny;
                boxes[num_boxes].x2 = maxx + 1;
                boxes[num_boxes].y2 = maxy + 1;
                boxes[num_boxes].area = area;
                num_boxes++;
            }
        }
    }

    if (!oom && num_boxes > 0) {
        int keep_th = imax(min_area, (int)(dominant_area * 0.0015));
        int ux1 = w, uy1 = h, ux2 = 0, uy2 = 0;
        int kept = 0;
        for (int b = 0; b < num_boxes; ++b) {
            if (boxes[b].area >= keep_th) {
                if (boxes[b].x1 < ux1) ux1 = boxes[b].x1;
                if (boxes[b].y1 < uy1) uy1 = boxes[b].y1;
                if (boxes[b].x2 > ux2) ux2 = boxes[b].x2;
                if (boxes[b].y2 > uy2) uy2 = boxes[b].y2;
                kept++;
            }
        }
        if (kept > 0) {
            int pad_x = imax(0, (int)llround((double)w * padding_ratio));
            int pad_y = imax(0, (int)llround((double)h * padding_ratio));
            ux1 = imax(0, ux1 - pad_x);
            uy1 = imax(0, uy1 - pad_y);
            ux2 = imin(w, ux2 + pad_x);
            uy2 = imin(h, uy2 + pad_y);
            if ((ux2 - ux1) >= w * 0.16 && (uy2 - uy1) >= h * 0.16) {
                if (!(ux1 <= w * 0.005 && uy1 <= h * 0.005 && ux2 >= w * 0.995 && uy2 >= h * 0.995)) {
                    res_x1 = imax(0, imin(width - 1, ux1 * step));
                    res_y1 = imax(0, imin(height - 1, uy1 * step));
                    res_x2 = imax(res_x1 + 1, imin(width, ux2 * step));
                    res_y2 = imax(res_y1 + 1, imin(height, uy2 * step));
                }
            }
        }
    }

    if (boxes != stack_boxes) free(boxes);
    if (queue != stack_q) free(queue);
    free(mask);
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);

    if (oom) {
        PyErr_NoMemory();
        return NULL;
    }

    return Py_BuildValue("(iiii)", res_x1, res_y1, res_x2, res_y2);
}

static PyMethodDef IllustMethods[] = {
    {"detect_illustration_bounds", py_detect_illustration_bounds, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef c_illust_module = {
    PyModuleDef_HEAD_INIT,
    "c_illust",
    NULL,
    -1,
    IllustMethods
};

PyMODINIT_FUNC PyInit_c_illust(void) {
    return PyModule_Create(&c_illust_module);
}