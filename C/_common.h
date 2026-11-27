#ifndef UNBOOK_COMMON_H
#define UNBOOK_COMMON_H

static inline int imin(int a, int b) { return a < b ? a : b; }
static inline int imax(int a, int b) { return a > b ? a : b; }

static inline int is_white_pixel(const unsigned char *p, int th) {
    return (p[0] >= th) & (p[1] >= th) & (p[2] >= th);
}

static inline int calc_gray_rgb(int r, int g, int b) {
    return (r * 77 + g * 150 + b * 29) >> 8;
}

static inline int calc_gray(const unsigned char *p) {
    return (p[0] * 77 + p[1] * 150 + p[2] * 29) >> 8;
}

static inline int calc_color_diff_rgb(int r, int g, int b) {
    int mx = r > g ? r : g;
    int mn = r < g ? r : g;
    if (b > mx) mx = b;
    if (b < mn) mn = b;
    return mx - mn;
}

static inline int calc_color_diff(const unsigned char *p) {
    return calc_color_diff_rgb(p[0], p[1], p[2]);
}

static inline int is_hsv_vivid_rgb(int r, int g, int b) {
    int mx = r > g ? r : g;
    if (b > mx) mx = b;
    if (mx <= 32) return 0;
    int mn = r < g ? r : g;
    if (b < mn) mn = b;
    return ((mx - mn) * 255) > (38 * mx);
}

static inline int is_hsv_vivid(const unsigned char *p) {
    return is_hsv_vivid_rgb(p[0], p[1], p[2]);
}

#endif