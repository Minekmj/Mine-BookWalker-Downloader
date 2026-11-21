#ifndef UNBOOK_COMMON_H
#define UNBOOK_COMMON_H

static inline int imin(int a, int b) { return a < b ? a : b; }
static inline int imax(int a, int b) { return a > b ? a : b; }

static inline int is_white_pixel(const unsigned char *p, int th) {
    return (p[0] >= th && p[1] >= th && p[2] >= th);
}

static inline int calc_gray(const unsigned char *p) {
    return (p[0] * 77 + p[1] * 150 + p[2] * 29) >> 8;
}

static inline int calc_color_diff(const unsigned char *p) {
    int r = p[0], g = p[1], b = p[2];
    int mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
    int mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
    return mx - mn;
}

static inline int is_hsv_vivid(const unsigned char *p) {
    int r = p[0], g = p[1], b = p[2];
    int mx = r > g ? (r > b ? r : b) : (g > b ? g : b);
    if (mx <= 32) return 0;
    int mn = r < g ? (r < b ? r : b) : (g < b ? g : b);
    return ((mx - mn) * 255) > (38 * mx);
}

#endif