from typing import Optional, Tuple

import numpy as np
from PIL import Image


def find_safe_split_pos(img: Image.Image, vertical_text: bool) -> Optional[int]:
    arr = np.asarray(img.convert("L"))
    h, w = arr.shape
    if vertical_text:
        if w < 120:
            return None
        y0, y1 = int(h * 0.02), max(int(h * 0.02) + 1, int(h * 0.98))
        band = arr[y0:y1, :]
        ink = (band < 230).sum(axis=0)
        lo, hi = int(w * 0.25), int(w * 0.75)
        tol = max(1, int(band.shape[0] * 0.002))
        center = w / 2.0
        span = hi - lo
    else:
        if h < 120:
            return None
        x0, x1 = int(w * 0.02), max(int(w * 0.02) + 1, int(w * 0.98))
        band = arr[:, x0:x1]
        ink = (band < 230).sum(axis=1)
        lo, hi = int(h * 0.25), int(h * 0.75)
        tol = max(1, int(band.shape[1] * 0.002))
        center = h / 2.0
        span = hi - lo
    if span <= 4:
        return None
    gaps = []
    start = None
    for idx in range(lo, hi):
        if ink[idx] <= tol:
            if start is None:
                start = idx
        else:
            if start is not None:
                gaps.append((start, idx - 1))
                start = None
    if start is not None:
        gaps.append((start, hi - 1))
    if gaps:
        best = min(gaps, key=lambda g: abs((g[0] + g[1]) / 2.0 - center) - (g[1] - g[0] + 1) * 0.25)
        return int((best[0] + best[1]) // 2)
    sub = ink[lo:hi]
    min_idx = int(np.argmin(sub))
    band_len = band.shape[0] if vertical_text else band.shape[1]
    if sub[min_idx] <= max(2, int(band_len * 0.03)):
        return lo + min_idx
    return None


def split_page_image_safe(img: Image.Image, vertical_text: bool) -> Optional[Tuple[Image.Image, Image.Image]]:
    pos = find_safe_split_pos(img, vertical_text)
    if pos is None:
        return None
    if vertical_text:
        right_img = img.crop((pos, 0, img.width, img.height))
        left_img = img.crop((0, 0, pos, img.height))
        return right_img, left_img
    top_img = img.crop((0, 0, img.width, pos))
    bottom_img = img.crop((0, pos, img.width, img.height))
    return top_img, bottom_img
