#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include "_common.h"

static int detect_header_cut_impl(const unsigned char *data, int w, int buf_h, int full_h, double top_pct) {
    int band_h = (int)((double)full_h * top_pct / 100.0 + 0.5);
    if (band_h < 2 || band_h > buf_h) {
        if (band_h < 2) return 0;
        band_h = buf_h;
    }

    int scan_h = (int)((double)full_h * (top_pct + 2.8) / 100.0 + 0.5);
    scan_h = imin(buf_h, imax(band_h + 6, scan_h));

    int *counts = (int *)calloc((size_t)scan_h * 2, sizeof(int));
    if (!counts) {
        return -1;
    }
    int *row_ink = counts;
    int *row_col = counts + scan_h;

    for (int y = 0; y < scan_h; ++y) {
        const unsigned char *row = data + (size_t)y * w * 3;
        int ink_cnt = 0;
        int col_cnt = 0;
        for (int x = 0; x < w; ++x) {
            const unsigned char *p = row + (size_t)x * 3;
            int g = calc_gray(p);
            int cd = calc_color_diff(p);
            if (g < 210 || cd > 24) ink_cnt++;
            if (cd > 24) col_cnt++;
        }
        row_ink[y] = ink_cnt;
        row_col[y] = col_cnt;
    }

    int ink_row_th = imax(2, w / 350);
    int first_ink_y = -1;
    int band_ink_rows = 0;
    for (int y = 0; y < band_h; ++y) {
        if (row_ink[y] > ink_row_th) {
            if (first_ink_y == -1) first_ink_y = y;
            band_ink_rows++;
        }
    }

    if (band_ink_rows < 2 || first_ink_y == -1) {
        free(counts);
        return 0;
    }

    int min_gap = imax(2, full_h / 450);
    int sep_start = -1;
    int run = 0;
    int search_start = imax(first_ink_y + 3, band_h / 3);

    for (int y = search_start; y < scan_h; ++y) {
        if (row_ink[y] <= ink_row_th) {
            if (run == 0) sep_start = y;
            run++;
            if (run >= min_gap) break;
        } else {
            run = 0;
            sep_start = -1;
        }
    }

    int result_cut = 0;
    if (run >= min_gap && sep_start > first_ink_y) {
        int header_h = sep_start - first_ink_y;
        long long total_hdr_ink = 0;
        long long total_hdr_col = 0;
        int max_row_ink = 0;
        for (int y = first_ink_y; y < sep_start; ++y) {
            total_hdr_ink += row_ink[y];
            total_hdr_col += row_col[y];
            if (row_ink[y] > max_row_ink) max_row_ink = row_ink[y];
        }
        double area = (double)header_h * (double)w;
        double avg_ink = (double)total_hdr_ink / area;
        double avg_col = (double)total_hdr_col / area;
        int is_frame_line = (header_h <= 6 && max_row_ink > (int)(w * 0.45));
        if (!is_frame_line && header_h <= imax(6, (int)(full_h * 0.045)) && avg_ink < 0.40 && avg_col < 0.08) {
            result_cut = imin(scan_h, sep_start + 2);
            if (result_cut < band_h) {
                int clean_at_band = 1;
                for (int y = sep_start; y < band_h; ++y) {
                    if (row_ink[y] > ink_row_th) {
                        clean_at_band = 0;
                        break;
                    }
                }
                if (clean_at_band) result_cut = band_h;
            }
        }
    }

    free(counts);
    return result_cut;
}

static PyObject *py_detect_header_cut_band(PyObject *self, PyObject *args) {
    Py_buffer view;
    int w, buf_h, full_h;
    double top_pct;

    if (!PyArg_ParseTuple(args, "y*iiid", &view, &w, &buf_h, &full_h, &top_pct)) {
        return NULL;
    }

    if (!PyBuffer_IsContiguous(&view, 'C')) {
        PyBuffer_Release(&view);
        PyErr_SetString(PyExc_ValueError, "Buffer must be C-contiguous");
        return NULL;
    }

    if (w < 20 || full_h < 40 || buf_h < 2 || top_pct <= 0.0 || view.len < (Py_ssize_t)w * buf_h * 3) {
        PyBuffer_Release(&view);
        return PyLong_FromLong(0);
    }

    const unsigned char *data = (const unsigned char *)view.buf;
    int res;
    Py_BEGIN_ALLOW_THREADS
    res = detect_header_cut_impl(data, w, buf_h, full_h, top_pct);
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);
    if (res < 0) {
        PyErr_NoMemory();
        return NULL;
    }
    return PyLong_FromLong(res);
}

static PyMethodDef HeaderMethods[] = {
    {"detect_header_cut_band", py_detect_header_cut_band, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef c_header_module = {
    PyModuleDef_HEAD_INIT,
    "c_header",
    NULL,
    -1,
    HeaderMethods
};

PyMODINIT_FUNC PyInit_c_header(void) {
    return PyModule_Create(&c_header_module);
}
