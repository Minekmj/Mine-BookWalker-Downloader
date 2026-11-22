from typing import Tuple

import cv2
import numpy as np
from PIL import Image

from core.vision.fast_detector.c_bridge import c_header, c_margins, ensure_rgb


def fast_is_blank(img: Image.Image, white_threshold: int = 248) -> bool:
    w, h = img.size
    if w <= 0 or h <= 0:
        return True
    rgb = ensure_rgb(img)
    if c_margins is not None:
        try:
            return bool(c_margins.is_blank_fast(rgb.tobytes(), w, h, int(white_threshold)))
        except Exception:
            pass
    small = rgb.resize((64, 64))
    arr = np.asarray(small)
    return float(np.mean(np.min(arr, axis=2) < white_threshold)) < 0.002


def fast_trim_bounds(
    img: Image.Image,
    white_threshold: int = 240,
    noise_ratio: float = 0.0015,
    padding: int = 1,
) -> Tuple[int, int, int, int]:
    w, h = img.size
    if w < 10 or h < 10:
        return (0, 0, w, h)
    rgb = ensure_rgb(img)
    if c_margins is not None:
        try:
            return c_margins.find_trim_bounds(
                rgb.tobytes(), w, h, int(white_threshold), float(noise_ratio), int(padding)
            )
        except Exception:
            pass
    arr = np.asarray(rgb)
    is_white = np.min(arr, axis=2) >= white_threshold
    non_white = ~is_white
    row_ratios = np.mean(non_white, axis=1)
    col_ratios = np.mean(non_white, axis=0)
    y_indices = np.where(row_ratios > noise_ratio)[0]
    x_indices = np.where(col_ratios > noise_ratio)[0]
    if len(y_indices) == 0 or len(x_indices) == 0:
        return (0, 0, w, h)
    y1 = max(0, int(y_indices[0]) - padding)
    y2 = min(h, int(y_indices[-1]) + 1 + padding)
    x1 = max(0, int(x_indices[0]) - padding)
    x2 = min(w, int(x_indices[-1]) + 1 + padding)
    if x2 - x1 < 10 or y2 - y1 < 10:
        return (0, 0, w, h)
    return (x1, y1, x2, y2)


def fast_has_center_gutter(img: Image.Image, white_threshold: int = 235) -> bool:
    w, h = img.size
    if w < 40 or h < 40:
        return False
    rgb = ensure_rgb(img)
    if c_margins is not None and hasattr(c_margins, "has_center_gutter_fast"):
        try:
            return bool(c_margins.has_center_gutter_fast(rgb.tobytes(), w, h, int(white_threshold)))
        except Exception:
            pass
    x1 = int(w * 0.46)
    x2 = int(w * 0.54)
    if x2 <= x1:
        return False
    strip = rgb.crop((x1, 0, x2, h))
    sw, sh = strip.size
    scale = min(1.0, 600.0 / max(1, sh))
    if scale < 1.0:
        strip = strip.resize((max(4, int(sw * scale)), max(40, int(sh * scale))), Image.Resampling.BILINEAR)
    arr = np.asarray(strip)
    is_white = np.min(arr, axis=2) >= white_threshold
    col_white_ratio = np.mean(is_white, axis=0)
    return bool(np.any(col_white_ratio >= 0.97))


def fast_detect_header_cut(img: Image.Image, top_pct: float) -> int:
    w, h = img.size
    if w < 20 or h < 40 or top_pct <= 0.0:
        return 0
    band_h = max(2, int(round(h * top_pct / 100.0)))
    scan_h = min(h, max(band_h + 6, int(round(h * (top_pct + 2.8) / 100.0))))
    top_band = ensure_rgb(img.crop((0, 0, w, scan_h)))
    if c_header is not None:
        try:
            return int(c_header.detect_header_cut_band(top_band.tobytes(), w, scan_h, h, float(top_pct)))
        except Exception:
            pass
    arr = np.asarray(top_band)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    cd = np.max(arr, axis=2).astype(np.int16) - np.min(arr, axis=2).astype(np.int16)
    ink = (gray < 210) | (cd > 24)
    row_ink = np.sum(ink, axis=1)
    row_col = np.sum(cd > 24, axis=1)
    ink_row_th = max(2, w // 350)
    band_ink = np.where(row_ink[:band_h] > ink_row_th)[0]
    if len(band_ink) < 2:
        return 0
    first_ink_y = int(band_ink[0])
    min_gap = max(2, h // 450)
    search_start = max(first_ink_y + 3, band_h // 3)
    run = 0
    sep_start = -1
    for y in range(search_start, scan_h):
        if row_ink[y] <= ink_row_th:
            if run == 0:
                sep_start = y
            run += 1
            if run >= min_gap:
                break
        else:
            run = 0
            sep_start = -1
    if run < min_gap or sep_start <= first_ink_y:
        return 0
    header_h = sep_start - first_ink_y
    avg_ink = float(np.sum(row_ink[first_ink_y:sep_start])) / float(header_h * w)
    avg_col = float(np.sum(row_col[first_ink_y:sep_start])) / float(header_h * w)
    max_row_ink = int(np.max(row_ink[first_ink_y:sep_start]))
    is_frame = header_h <= 6 and max_row_ink > int(w * 0.45)
    if not is_frame and header_h <= max(6, int(h * 0.045)) and avg_ink < 0.40 and avg_col < 0.08:
        res = min(scan_h, sep_start + 2)
        if res < band_h and not np.any(row_ink[sep_start:band_h] > ink_row_th):
            res = band_h
        return res
    return 0
