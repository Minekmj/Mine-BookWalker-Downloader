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

static int morph_box_inplace(unsigned char *buf, int w, int h, int radius, int is_erode) {
    int ksize = radius * 2 + 1;
    unsigned char *row_tmp = (unsigned char *)malloc((size_t)w);
    int *col_sum = (int *)calloc((size_t)w, sizeof(int));
    unsigned char *ring = (unsigned char *)malloc((size_t)ksize * (size_t)w);
    if (!row_tmp || !col_sum || !ring) {
        free(row_tmp);
        free(col_sum);
        free(ring);
        return -1;
    }

    for (int y = 0; y < h; ++y) {
        unsigned char *row = buf + (size_t)y * w;
        int sum = 0;
        for (int x = 0; x <= imin(w - 1, radius); ++x) {
            sum += row[x];
        }
        for (int x = 0; x < w; ++x) {
            int lx = imax(0, x - radius);
            int rx = imin(w - 1, x + radius);
            int cnt = rx - lx + 1;
            row_tmp[x] = is_erode ? (sum == cnt ? 1 : 0) : (sum > 0 ? 1 : 0);
            int out_x = x - radius;
            int in_x = x + radius + 1;
            if (out_x >= 0) sum -= row[out_x];
            if (in_x < w) sum += row[in_x];
        }
        memcpy(row, row_tmp, (size_t)w);
    }

    for (int y = 0; y <= imin(h - 1, radius); ++y) {
        const unsigned char *srow = buf + (size_t)y * w;
        unsigned char *rrow = ring + (size_t)(y % ksize) * w;
        memcpy(rrow, srow, (size_t)w);
        for (int x = 0; x < w; ++x) {
            col_sum[x] += srow[x];
        }
    }

    for (int y = 0; y < h; ++y) {
        int ty = imax(0, y - radius);
        int by = imin(h - 1, y + radius);
        int cnt = by - ty + 1;
        unsigned char *drow = buf + (size_t)y * w;
        if (is_erode) {
            for (int x = 0; x < w; ++x) {
                drow[x] = (col_sum[x] == cnt) ? 1 : 0;
            }
        } else {
            for (int x = 0; x < w; ++x) {
                drow[x] = (col_sum[x] > 0) ? 1 : 0;
            }
        }
        int out_y = y - radius;
        if (out_y >= 0) {
            const unsigned char *orow = ring + (size_t)(out_y % ksize) * w;
            for (int x = 0; x < w; ++x) {
                col_sum[x] -= orow[x];
            }
        }
        int in_y = y + radius + 1;
        if (in_y < h) {
            const unsigned char *irow = buf + (size_t)in_y * w;
            unsigned char *rrow = ring + (size_t)(in_y % ksize) * w;
            memcpy(rrow, irow, (size_t)w);
            for (int x = 0; x < w; ++x) {
                col_sum[x] += irow[x];
            }
        }
    }

    free(row_tmp);
    free(col_sum);
    free(ring);
    return 0;
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
    if (!mask) {
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }

    const unsigned char *data = (const unsigned char *)view.buf;
    int oom = 0;

    Py_BEGIN_ALLOW_THREADS
    int patch_h = imax(2, (int)(h * 0.035));
    int patch_w = imax(2, (int)(w * 0.035));
    int hist_g[256] = {0};
    int hist_r[256] = {0};
    int hist_gr[256] = {0};
    int hist_b[256] = {0};
    int border_cnt = 0;

    for (int py = 0; py < patch_h; ++py) {
        int sys[2] = {py, h - patch_h + py};
        for (int yi = 0; yi < 2; ++yi) {
            int y = imin(height - 1, sys[yi] * step);
            const unsigned char *src_row = data + (size_t)y * width * 3;
            for (int px = 0; px < patch_w; ++px) {
                int sxs[2] = {px, w - patch_w + px};
                for (int xi = 0; xi < 2; ++xi) {
                    int x = imin(width - 1, sxs[xi] * step);
                    const unsigned char *p = src_row + (size_t)x * 3;
                    hist_g[calc_gray(p)]++;
                    hist_r[p[0]]++;
                    hist_gr[p[1]]++;
                    hist_b[p[2]]++;
                    border_cnt++;
                }
            }
        }
    }

    int bg_gray = hist_median(hist_g, border_cnt);
    if (bg_gray >= 205) {
        int th = imax(170, imin(248, bg_gray - 11));
        for (int sy = 0; sy < h; ++sy) {
            int y = imin(height - 1, sy * step);
            const unsigned char *src_row = data + (size_t)y * width * 3;
            unsigned char *mrow = mask + (size_t)sy * w;
            for (int sx = 0; sx < w; ++sx) {
                int x = imin(width - 1, sx * step);
                const unsigned char *p = src_row + (size_t)x * 3;
                if (calc_gray(p) < th || is_hsv_vivid(p)) {
                    mrow[sx] = 1;
                }
            }
        }
    } else {
        int bg_r = hist_median(hist_r, border_cnt);
        int bg_gr = hist_median(hist_gr, border_cnt);
        int bg_b = hist_median(hist_b, border_cnt);
        for (int sy = 0; sy < h; ++sy) {
            int y = imin(height - 1, sy * step);
            const unsigned char *src_row = data + (size_t)y * width * 3;
            unsigned char *mrow = mask + (size_t)sy * w;
            for (int sx = 0; sx < w; ++sx) {
                int x = imin(width - 1, sx * step);
                const unsigned char *p = src_row + (size_t)x * 3;
                int dr = abs((int)p[0] - bg_r);
                int dg = abs((int)p[1] - bg_gr);
                int db = abs((int)p[2] - bg_b);
                if (imax(dr, imax(dg, db)) > 22) {
                    mrow[sx] = 1;
                }
            }
        }
    }
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);

    int res_x1 = 0, res_y1 = 0, res_x2 = width, res_y2 = height;

    Py_BEGIN_ALLOW_THREADS
    int ksize = imax(3, imin(13, (imin(w, h) / 100) | 1));
    int radius = ksize / 2;
    if (morph_box_inplace(mask, w, h, radius, 0) < 0 ||
        morph_box_inplace(mask, w, h, radius, 0) < 0 ||
        morph_box_inplace(mask, w, h, radius, 1) < 0 ||
        morph_box_inplace(mask, w, h, radius, 1) < 0) {
        oom = 1;
    }

    size_t q_cap = total < 8192 ? total : 8192;
    uint32_t *queue = oom ? NULL : (uint32_t *)malloc(q_cap * sizeof(uint32_t));
    int cap_boxes = 64;
    int num_boxes = 0;
    CompBox *boxes = oom ? NULL : (CompBox *)malloc((size_t)cap_boxes * sizeof(CompBox));
    if (!oom && (!queue || !boxes)) {
        oom = 1;
    }

    if (!oom) {
        int min_area = imax(12, (int)((double)total * 0.000035));
        const int dx8[8] = {-1, 0, 1, -1, 1, -1, 0, 1};
        const int dy8[8] = {-1, -1, -1, 0, 0, 1, 1, 1};
        int dominant_area = 0;

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
                                        uint32_t *nq = (uint32_t *)realloc(queue, new_cap * sizeof(uint32_t));
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
                        if (oom) break;
                    }
                    if (oom) break;
                    int bw = maxx - minx + 1;
                    int bh = maxy - miny + 1;
                    int area = (int)tail;
                    if (area < min_area && !(bw >= w * 0.035 && bh >= h * 0.035)) continue;
                    if (bw < w * 0.004 && bh < h * 0.012) continue;
                    if ((minx == 0 || maxx + 1 >= w) && bw <= w * 0.015 && bh >= h * 0.25) continue;
                    if ((miny == 0 || maxy + 1 >= h) && bh <= h * 0.015 && bw >= w * 0.25) continue;
                    if (area > dominant_area) dominant_area = area;
                    if (num_boxes >= cap_boxes) {
                        int new_cap = cap_boxes * 2;
                        CompBox *nb = (CompBox *)realloc(boxes, (size_t)new_cap * sizeof(CompBox));
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
    }

    free(boxes);
    free(queue);
    free(mask);
    Py_END_ALLOW_THREADS

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