from typing import Tuple

import cv2
import numpy as np
from PIL import Image

from core.vision.fast_detector.c_bridge import c_illust, ensure_rgb


def fast_detect_illustration_bounds(
    img: Image.Image,
    padding_ratio: float = 0.006,
) -> Tuple[int, int, int, int]:
    rgb = ensure_rgb(img)
    width, height = rgb.size
    if width < 40 or height < 40:
        return (0, 0, width, height)
    if c_illust is not None:
        try:
            return c_illust.detect_illustration_bounds(rgb.tobytes(), width, height, float(padding_ratio))
        except Exception:
            pass
    scale = min(1.0, 800.0 / max(width, height))
    small = rgb.resize((max(40, int(width * scale)), max(40, int(height * scale))), Image.Resampling.BILINEAR) if scale < 1.0 else rgb
    arr = np.asarray(small)
    h, w = arr.shape[:2]
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    patch_h = max(2, int(h * 0.035))
    patch_w = max(2, int(w * 0.035))
    border = np.concatenate((gray[:patch_h, :patch_w].ravel(), gray[:patch_h, -patch_w:].ravel(), gray[-patch_h:, :patch_w].ravel(), gray[-patch_h:, -patch_w:].ravel()))
    bg = float(np.median(border))
    if bg >= 205:
        threshold = max(170, min(248, int(bg - 11)))
        mask = (gray < threshold).astype(np.uint8)
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        color_mask = ((hsv[:, :, 1] > 38) & (hsv[:, :, 2] > 32)).astype(np.uint8)
        mask = np.maximum(mask, color_mask)
    else:
        border_rgb = np.concatenate((arr[:patch_h, :patch_w].reshape(-1, 3), arr[:patch_h, -patch_w:].reshape(-1, 3), arr[-patch_h:, :patch_w].reshape(-1, 3), arr[-patch_h:, -patch_w:].reshape(-1, 3)), axis=0)
        bg_rgb = np.median(border_rgb, axis=0).astype(np.int16)
        distance = np.max(np.abs(arr.astype(np.int16) - bg_rgb), axis=2)
        mask = (distance > 22).astype(np.uint8)
    kernel_size = max(3, min(13, (min(w, h) // 100) | 1))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return (0, 0, width, height)
    total = w * h
    min_area = max(12, int(total * 0.000035))
    selected = []
    for index in range(1, count):
        x, y, box_w, box_h, area = [int(value) for value in stats[index]]
        if area < min_area and not (box_w >= w * 0.035 and box_h >= h * 0.035):
            continue
        if box_w < w * 0.004 and box_h < h * 0.012:
            continue
        if (x == 0 or x + box_w >= w) and box_w <= w * 0.015 and box_h >= h * 0.25:
            continue
        if (y == 0 or y + box_h >= h) and box_h <= h * 0.015 and box_w >= w * 0.25:
            continue
        selected.append((x, y, x + box_w, y + box_h, area))
    if not selected:
        return (0, 0, width, height)
    selected.sort(key=lambda item: item[4], reverse=True)
    dominant_area = selected[0][4]
    selected = [item for item in selected if item[4] >= max(min_area, dominant_area * 0.0015)]
    x1 = min(item[0] for item in selected)
    y1 = min(item[1] for item in selected)
    x2 = max(item[2] for item in selected)
    y2 = max(item[3] for item in selected)
    pad_x = max(0, int(round(w * padding_ratio)))
    pad_y = max(0, int(round(h * padding_ratio)))
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(w, x2 + pad_x)
    y2 = min(h, y2 + pad_y)
    if x2 - x1 < w * 0.16 or y2 - y1 < h * 0.16:
        return (0, 0, width, height)
    if x1 <= w * 0.005 and y1 <= h * 0.005 and x2 >= w * 0.995 and y2 >= h * 0.995:
        return (0, 0, width, height)
    if scale < 1.0:
        x1, y1, x2, y2 = [int(round(value / scale)) for value in (x1, y1, x2, y2)]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return (x1, y1, x2, y2)
