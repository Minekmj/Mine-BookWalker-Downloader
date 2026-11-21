#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
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

    const unsigned char *data = (const unsigned char *)view.buf;
    int step_x = imax(1, w / 64);
    int step_y = imax(1, h / 64);
    long long total = 0;
    long long non_white = 0;

    Py_BEGIN_ALLOW_THREADS
    for (int y = 0; y < h; y += step_y) {
        const unsigned char *row = data + (size_t)y * w * 3;
        for (int x = 0; x < w; x += step_x) {
            const unsigned char *p = row + (size_t)x * 3;
            total++;
            if (p[0] < th || p[1] < th || p[2] < th) {
                non_white++;
            }
        }
    }
    Py_END_ALLOW_THREADS

    PyBuffer_Release(&view);
    if (total == 0) {
        Py_RETURN_TRUE;
    }
    return PyBool_FromLong(((double)non_white / (double)total) < 0.002 ? 1 : 0);
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

    const unsigned char *data = (const unsigned char *)view.buf;
    int *counts = (int *)calloc((size_t)h + (size_t)w, sizeof(int));
    if (!counts) {
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }
    int *row_counts = counts;
    int *col_counts = counts + h;

    int step_y = h > 1000 ? 2 : 1;
    int step_x = w > 1000 ? 2 : 1;
    int y1 = -1, y2 = -1;
    int x1 = -1, x2 = -1;

    Py_BEGIN_ALLOW_THREADS
    for (int y = 0; y < h; y += step_y) {
        const unsigned char *row = data + (size_t)y * w * 3;
        int r_cnt = 0;
        for (int x = 0; x < w; x += step_x) {
            const unsigned char *p = row + (size_t)x * 3;
            if (!is_white_pixel(p, th)) {
                r_cnt++;
                col_counts[x]++;
            }
        }
        row_counts[y] = r_cnt;
    }

    int min_row_noise = (int)(((double)w / (double)step_x) * noise);
    int min_col_noise = (int)(((double)h / (double)step_y) * noise);

    for (int y = 0; y < h; y += step_y) {
        if (row_counts[y] > min_row_noise) {
            if (y1 == -1) y1 = y;
            y2 = y;
        }
    }

    for (int x = 0; x < w; x += step_x) {
        if (col_counts[x] > min_col_noise) {
            if (x1 == -1) x1 = x;
            x2 = x;
        }
    }
    Py_END_ALLOW_THREADS

    free(counts);
    PyBuffer_Release(&view);

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

    const unsigned char *data = (const unsigned char *)view.buf;
    int x1 = (int)(w * 0.46);
    int x2 = (int)(w * 0.54);
    int span = x2 - x1;
    if (span <= 0) {
        PyBuffer_Release(&view);
        Py_RETURN_FALSE;
    }
    int *white_cnt = (int *)calloc((size_t)span, sizeof(int));
    if (!white_cnt) {
        PyBuffer_Release(&view);
        PyErr_NoMemory();
        return NULL;
    }

    int step_y = h > 600 ? (h / 600) : 1;
    if (step_y < 1) step_y = 1;
    int sample_rows = (h + step_y - 1) / step_y;
    int min_white_rows = (int)ceil((double)sample_rows * 0.97);
    int found = 0;

    Py_BEGIN_ALLOW_THREADS
    for (int y = 0; y < h; y += step_y) {
        const unsigned char *row = data + ((size_t)y * w + x1) * 3;
        for (int i = 0; i < span; ++i) {
            const unsigned char *p = row + (size_t)i * 3;
            if (is_white_pixel(p, th)) {
                white_cnt[i]++;
            }
        }
    }
    for (int i = 0; i < span; ++i) {
        if (white_cnt[i] >= min_white_rows) {
            found = 1;
            break;
        }
    }
    Py_END_ALLOW_THREADS

    free(white_cnt);
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
