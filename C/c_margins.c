#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include "_common.h"

static PyObject *py_is_blank_fast(PyObject *self, PyObject *args) {
    Py_buffer view;
    int w, h, th;

    if (!PyArg_ParseTuple(args, "y*iii", &view, &w, &h, &th)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (w <= 0 || h <= 0 || view.len < (Py_ssize_t)w * h * 3) {
        PyBuffer_Release(&view);
        Py_RETURN_TRUE;
    }

    if (th <= 0) {
        PyBuffer_Release(&view);
        Py_RETURN_TRUE;
    }

    int step_x = imax(1, w / 64);
    int step_y = imax(1, h / 64);
    long long nx = ((long long)w + step_x - 1) / step_x;
    long long ny = ((long long)h + step_y - 1) / step_y;
    long long total = nx * ny;

    if (total == 0) {
        PyBuffer_Release(&view);
        Py_RETURN_TRUE;
    }

    if (th > 255) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }

    long long limit = (long long)((double)total * 0.002);
    while (limit > 0 && ((double)limit / (double)total) >= 0.002) limit--;
    while (((double)(limit + 1) / (double)total) < 0.002) limit++;

    const unsigned char *data = (const unsigned char *)view.buf;
    size_t row_stride = (size_t)w * 3 * (size_t)step_y;
    size_t col_stride = (size_t)step_x * 3;
    long long non_white = 0;

    Py_BEGIN_ALLOW_THREADS
    const unsigned char *row = data;
    for (long long iy = 0; iy < ny; ++iy, row += row_stride) {
        const unsigned char *p = row;
        for (long long ix = 0; ix < nx; ++ix, p += col_stride) {
            if (!is_white_pixel(p, th)) {
                if (++non_white > limit) {
                    goto done;
                }
            }
        }
    }
done:
    ;
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);
    return PyBool_FromLong(non_white <= limit ? 1 : 0);
}

static PyObject *py_find_trim_bounds(PyObject *self, PyObject *args) {
    Py_buffer view;
    int w, h, th, pad;
    double noise;

    if (!PyArg_ParseTuple(args, "y*iiidi", &view, &w, &h, &th, &noise, &pad)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (w < 10 || h < 10 || view.len < (Py_ssize_t)w * h * 3) {
        PyBuffer_Release(&view);
        return Py_BuildValue("(iiii)", 0, 0, w, h);
    }

    int step_y = h > 1000 ? 2 : 1;
    int step_x = w > 1000 ? 2 : 1;
    int nx = (w + step_x - 1) / step_x;
    int ny = (h + step_y - 1) / step_y;
    int min_row_noise = (int)(((double)w / (double)step_x) * noise);
    int min_col_noise = (int)(((double)h / (double)step_y) * noise);

    if (th <= 0 && min_row_noise >= 0 && min_col_noise >= 0) {
        PyBuffer_Release(&view);
        return Py_BuildValue("(iiii)", 0, 0, w, h);
    }

    int y1 = -1, y2 = -1;
    int x1 = -1, x2 = -1;

    if (th > 255) {
        PyBuffer_Release(&view);
        if (nx > min_row_noise && ny > min_col_noise) {
            y1 = 0;
            y2 = (ny - 1) * step_y;
            x1 = 0;
            x2 = (nx - 1) * step_x;
        }
    } else {
        int stack_cols[4096];
        int *col_counts = nx <= 4096 ? stack_cols : (int *)malloc((size_t)nx * sizeof(int));
        if (!col_counts) {
            PyBuffer_Release(&view);
            PyErr_NoMemory();
            return NULL;
        }
        memset(col_counts, 0, (size_t)nx * sizeof(int));

        const unsigned char *data = (const unsigned char *)view.buf;
        size_t row_stride = (size_t)w * 3 * (size_t)step_y;

        Py_BEGIN_ALLOW_THREADS
        const unsigned char *row = data;
        if (th >= 128) {
            const uint64_t mask_l = 0x7F7F7F7F7F7F7F7FULL;
            const uint64_t mask_m = 0x8080808080808080ULL;
            const uint64_t add_k = (uint64_t)(256 - th) * 0x0101010101010101ULL;

            if (step_x == 1) {
                for (int y = 0; y < h; y += step_y, row += row_stride) {
                    int r_cnt = 0;
                    int col = 0;
                    const unsigned char *p = row;
                    for (; col + 8 <= nx; col += 8, p += 24) {
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
                            int nw = (q[0] < th) | (q[1] < th) | (q[2] < th);
                            r_cnt += nw;
                            col_counts[col + k] += nw;
                        }
                    }
                    for (; col < nx; ++col, p += 3) {
                        int nw = (p[0] < th) | (p[1] < th) | (p[2] < th);
                        r_cnt += nw;
                        col_counts[col] += nw;
                    }
                    if (r_cnt > min_row_noise) {
                        if (y1 == -1) y1 = y;
                        y2 = y;
                    }
                }
            } else {
                int sw_limit = w / 2;
                for (int y = 0; y < h; y += step_y, row += row_stride) {
                    int r_cnt = 0;
                    int col = 0;
                    const unsigned char *p = row;
                    for (; col + 4 <= sw_limit; col += 4, p += 24) {
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
                        for (int k = 0; k < 4; ++k, q += 6) {
                            int nw = (q[0] < th) | (q[1] < th) | (q[2] < th);
                            r_cnt += nw;
                            col_counts[col + k] += nw;
                        }
                    }
                    for (; col < nx; ++col, p += 6) {
                        int nw = (p[0] < th) | (p[1] < th) | (p[2] < th);
                        r_cnt += nw;
                        col_counts[col] += nw;
                    }
                    if (r_cnt > min_row_noise) {
                        if (y1 == -1) y1 = y;
                        y2 = y;
                    }
                }
            }
        } else {
            size_t col_stride = (size_t)step_x * 3;
            for (int y = 0; y < h; y += step_y, row += row_stride) {
                int r_cnt = 0;
                const unsigned char *p = row;
                for (int col = 0; col < nx; ++col, p += col_stride) {
                    int nw = (p[0] < th) | (p[1] < th) | (p[2] < th);
                    r_cnt += nw;
                    col_counts[col] += nw;
                }
                if (r_cnt > min_row_noise) {
                    if (y1 == -1) y1 = y;
                    y2 = y;
                }
            }
        }

        for (int col = 0; col < nx; ++col) {
            if (col_counts[col] > min_col_noise) {
                if (x1 == -1) x1 = col * step_x;
                x2 = col * step_x;
            }
        }
        Py_END_ALLOW_THREADS

        if (col_counts != stack_cols) free(col_counts);
        PyBuffer_Release(&view);
    }

    if (y1 == -1 || x1 == -1) {
        return Py_BuildValue("(iiii)", 0, 0, w, h);
    }

    y1 = imax(0, y1 - pad - (step_y - 1));
    y2 = imin(h, y2 + step_y + pad);
    x1 = imax(0, x1 - pad - (step_x - 1));
    x2 = imin(w, x2 + step_x + pad);

    if (x2 - x1 < 10 || y2 - y1 < 10) {
        return Py_BuildValue("(iiii)", 0, 0, w, h);
    }

    return Py_BuildValue("(iiii)", x1, y1, x2, y2);
}

static PyObject *py_has_center_gutter_fast(PyObject *self, PyObject *args) {
    Py_buffer view;
    int w, h, th;

    if (!PyArg_ParseTuple(args, "y*iii", &view, &w, &h, &th)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (w < 40 || h < 40 || view.len < (Py_ssize_t)w * h * 3) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }

    int x1 = (int)(w * 0.46);
    int x2 = (int)(w * 0.54);
    int span = x2 - x1;
    if (span <= 0) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }

    int step_y = h > 600 ? (h / 600) : 1;
    if (step_y < 1) step_y = 1;
    int sample_rows = (h + step_y - 1) / step_y;
    int min_white_rows = (int)ceil((double)sample_rows * 0.97);
    int max_bad_rows = sample_rows - min_white_rows;

    if (min_white_rows <= 0) {
        PyBuffer_Release(&view);
        Py_RETURN_TRUE;
    }
    if (max_bad_rows < 0 || th > 255) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }
    if (th <= 0) {
        PyBuffer_Release(&view);
        Py_RETURN_TRUE;
    }

    int stack_bad[1024];
    int stack_act[1024];
    int *bad_cnt = span <= 1024 ? stack_bad : (int *)malloc((size_t)span * sizeof(int));
    int *active = span <= 1024 ? stack_act : (int *)malloc((size_t)span * sizeof(int));
    if (!bad_cnt || !active) {
        if (bad_cnt != stack_bad) free(bad_cnt);
        if (active != stack_act) free(active);
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }
    memset(bad_cnt, 0, (size_t)span * sizeof(int));

    const unsigned char *data = (const unsigned char *)view.buf;
    size_t row_stride = (size_t)w * 3 * (size_t)step_y;
    int found = 0;

    Py_BEGIN_ALLOW_THREADS
    const unsigned char *row = data + (size_t)x1 * 3;
    int n_active = span;
    int r = 0;

    if (th >= 128) {
        const uint64_t mask_l = 0x7F7F7F7F7F7F7F7FULL;
        const uint64_t mask_m = 0x8080808080808080ULL;
        const uint64_t add_k = (uint64_t)(256 - th) * 0x0101010101010101ULL;

        for (; r < sample_rows && n_active == span; ++r, row += row_stride) {
            int need_compact = 0;
            int i = 0;
            const unsigned char *p = row;
            for (; i + 8 <= span; i += 8, p += 24) {
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
                    if (!is_white_pixel(q, th)) {
                        if (++bad_cnt[i + k] > max_bad_rows) {
                            need_compact = 1;
                        }
                    }
                }
            }
            for (; i < span; ++i, p += 3) {
                if (!is_white_pixel(p, th)) {
                    if (++bad_cnt[i] > max_bad_rows) {
                        need_compact = 1;
                    }
                }
            }
            int rem = sample_rows - 1 - r;
            if (rem <= max_bad_rows) {
                for (int c = 0; c < span; ++c) {
                    if (bad_cnt[c] + rem <= max_bad_rows) {
                        found = 1;
                        break;
                    }
                }
                if (found) break;
            }
            if (need_compact) {
                int widx = 0;
                for (int c = 0; c < span; ++c) {
                    if (bad_cnt[c] <= max_bad_rows) {
                        active[widx++] = c;
                    }
                }
                n_active = widx;
                if (n_active == 0) break;
            }
        }
        if (n_active == span && r < sample_rows && !found) {
            r++;
            row += row_stride;
        }
    } else {
        for (; r < sample_rows && n_active == span; ++r, row += row_stride) {
            int need_compact = 0;
            const unsigned char *p = row;
            for (int i = 0; i < span; ++i, p += 3) {
                if (!is_white_pixel(p, th)) {
                    if (++bad_cnt[i] > max_bad_rows) {
                        need_compact = 1;
                    }
                }
            }
            int rem = sample_rows - 1 - r;
            if (rem <= max_bad_rows) {
                for (int c = 0; c < span; ++c) {
                    if (bad_cnt[c] + rem <= max_bad_rows) {
                        found = 1;
                        break;
                    }
                }
                if (found) break;
            }
            if (need_compact) {
                int widx = 0;
                for (int c = 0; c < span; ++c) {
                    if (bad_cnt[c] <= max_bad_rows) {
                        active[widx++] = c;
                    }
                }
                n_active = widx;
                if (n_active == 0) break;
            }
        }
    }

    if (!found && n_active > 0 && n_active < span) {
        if (th < 128 && r == sample_rows) {
            r = sample_rows;
        } else {
            for (; r < sample_rows; ++r, row += row_stride) {
                int rem = sample_rows - 1 - r;
                int widx = 0;
                for (int k = 0; k < n_active; ++k) {
                    int c = active[k];
                    const unsigned char *p = row + (size_t)c * 3;
                    int bc = bad_cnt[c];
                    if (!is_white_pixel(p, th)) {
                        bc++;
                        bad_cnt[c] = bc;
                        if (bc > max_bad_rows) continue;
                    }
                    if (bc + rem <= max_bad_rows) {
                        found = 1;
                        break;
                    }
                    active[widx++] = c;
                }
                if (found) break;
                n_active = widx;
                if (n_active == 0) break;
            }
        }
    }
    Py_END_ALLOW_THREADS

    if (bad_cnt != stack_bad) free(bad_cnt);
    if (active != stack_act) free(active);
    PyBuffer_Release(&view);
    return PyBool_FromLong(found);
}

static PyMethodDef MarginsMethods[] = {
    {"is_blank_fast", py_is_blank_fast, METH_VARARGS, NULL},
    {"find_trim_bounds", py_find_trim_bounds, METH_VARARGS, NULL},
    {"has_center_gutter_fast", py_has_center_gutter_fast, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef c_margins_module = {
    PyModuleDef_HEAD_INIT,
    "c_margins",
    NULL,
    -1,
    MarginsMethods
};

PyMODINIT_FUNC PyInit_c_margins(void) {
    return PyModule_Create(&c_margins_module);
}