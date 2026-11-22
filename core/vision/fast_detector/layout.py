from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from core.vision.fast_detector.c_bridge import c_layout, ensure_rgb


def fast_analyze_page(
    img: Image.Image,
    sensitivity: str = "normal",
    small_illust: bool = False,
    orig_size: Optional[Tuple[int, int]] = None,
) -> Tuple[bool, str, float, float, float, float]:
    w, h = img.size
    if w < 10 or h < 10:
        return False, "텍스트 추정", 0.0, 0.0, 0.0, 0.0
    orig_w, orig_h = orig_size if orig_size else (w, h)
    sens_map = {"conservative": 0, "normal": 1, "sensitive": 2}
    sens_idx = sens_map.get(sensitivity, 1)
    rgb = ensure_rgb(img)
    if c_layout is not None:
        try:
            is_ill, code, ink_r, col_r, mid_r, blob_r, _ = c_layout.analyze_page_fast(
                rgb.tobytes(), w, h, sens_idx, 1 if small_illust else 0, int(orig_w), int(orig_h)
            )
            reasons = {
                0: "본문 텍스트",
                1: f"컬러 이미지 ({col_r*100:.1f}%)",
                2: f"큰 그림 영역 감지 ({blob_r*100:.2f}%)",
                3: f"단독 소형 삽화 감지 ({blob_r*100:.2f}%)",
                4: "흑백 삽화/음영 밀도 높음",
            }
            return bool(is_ill), reasons.get(code, "텍스트 추정"), col_r, ink_r, blob_r, mid_r
        except Exception:
            pass

    scale = min(1.0, 800.0 / max(w, h, orig_w, orig_h))
    if scale < 1.0:
        resized = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.BILINEAR)
        s_orig_w, s_orig_h = max(1, int(orig_w * scale)), max(1, int(orig_h * scale))
    else:
        resized = rgb
        s_orig_w, s_orig_h = orig_w, orig_h
    arr = np.asarray(resized)
    sh, sw = arr.shape[:2]
    total_pixels = float(sw * sh)
    orig_pixels = float(max(1, s_orig_w * s_orig_h))
    diff = np.max(arr, axis=2).astype(np.int16) - np.min(arr, axis=2).astype(np.int16)
    color_mask = diff > 24
    color_ratio = float(np.mean(color_mask))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    fg = ((gray < 215) | color_mask).astype(np.uint8)
    ink_ratio = float(np.mean(fg))
    midtone_ratio = float(np.mean((gray >= 55) & (gray <= 200)))
    col_ink = np.sum(fg, axis=0)
    col_th = max(2, int(s_orig_h * 0.03))
    max_narrow_w = max(3, int(s_orig_w * 0.075))
    text_col_groups = 0
    in_grp = False
    grp_start = 0
    for sx in range(sw):
        if col_ink[sx] >= col_th:
            if not in_grp:
                in_grp = True
                grp_start = sx
        else:
            if in_grp:
                if sx - grp_start <= max_narrow_w:
                    text_col_groups += 1
                in_grp = False
    if in_grp and (sw - grp_start <= max_narrow_w):
        text_col_groups += 1
    c_labels, _, c_stats, _ = cv2.connectedComponentsWithStats(color_mask.astype(np.uint8), connectivity=8)
    max_c_area = float(np.max(c_stats[1:, cv2.CC_STAT_AREA])) if c_labels > 1 else 0.0
    largest_color_blob = max_c_area / total_pixels
    max_color_orig = max_c_area / orig_pixels
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    max_fg_blob = float(np.max(stats[1:, cv2.CC_STAT_AREA])) if num_labels > 1 else 0.0
    largest_blob_ratio = max_fg_blob / total_pixels
    max_blob_orig_ratio = max_fg_blob / orig_pixels
    dominant_art_box = False
    large_drawing_box = False
    small_drawing_box = False
    for idx in range(1, num_labels):
        cw, ch, carea = int(stats[idx, 2]), int(stats[idx, 3]), int(stats[idx, 4])
        area_orig = carea / orig_pixels
        if cw >= s_orig_w * 0.40 and ch >= s_orig_h * 0.35 and area_orig >= 0.12:
            dominant_art_box = True
        if cw >= s_orig_w * 0.30 and ch >= s_orig_h * 0.25 and area_orig >= 0.08:
            large_drawing_box = True
        if small_illust and carea >= 4 and cw >= s_orig_w * 0.065 and ch >= s_orig_h * 0.045:
            small_drawing_box = True
    presets = {
        "conservative": {"color": 0.05, "color_full": 0.22, "color_blob": 0.008, "blob": 0.025, "ink": 0.36, "mid": 0.18},
        "normal": {"color": 0.025, "color_full": 0.16, "color_blob": 0.0045, "blob": 0.012, "ink": 0.28, "mid": 0.12},
        "sensitive": {"color": 0.015, "color_full": 0.10, "color_blob": 0.003, "blob": 0.006, "ink": 0.22, "mid": 0.08},
    }
    th = presets.get(sensitivity, presets["normal"])
    is_thin_text_strip = (sw < s_orig_w * 0.065) or (sh < s_orig_h * 0.045)
    has_any_text = text_col_groups >= 1
    has_substantive_text = text_col_groups >= 3
    is_compact = (small_illust and not has_substantive_text and not is_thin_text_strip and sw <= s_orig_w * 0.42 and sh <= s_orig_h * 0.45 and sw >= s_orig_w * 0.09 and sh >= s_orig_h * 0.08 and ink_ratio >= 0.16)
    if is_thin_text_strip and color_ratio < 0.08 and max_blob_orig_ratio < 0.006 and not small_drawing_box:
        return False, "본문 텍스트", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if is_compact and small_drawing_box and not has_substantive_text:
        return True, f"단독 소형 삽화 감지 ({largest_blob_ratio*100:.2f}%)", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if has_substantive_text and not dominant_art_box and color_ratio < 0.12:
        return False, "본문 텍스트", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if has_any_text and not dominant_art_box and not large_drawing_box and max_blob_orig_ratio < 0.10 and color_ratio < 0.10 and not (ink_ratio >= 0.30 and midtone_ratio >= 0.12):
        return False, "본문 텍스트", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if color_ratio >= th["color_full"] or (color_ratio >= th["color"] and (largest_color_blob >= th["color_blob"] or max_color_orig >= 0.005) and (not has_any_text or color_ratio >= 0.10)):
        return True, f"컬러 이미지 ({color_ratio*100:.1f}%)", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if dominant_art_box or large_drawing_box or (not has_any_text and not is_thin_text_strip and largest_blob_ratio >= th["blob"] and max_blob_orig_ratio >= 0.006):
        return True, f"큰 그림 영역 감지 ({largest_blob_ratio*100:.2f}%)", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if small_illust and not has_any_text and not is_thin_text_strip and small_drawing_box:
        return True, f"단독 소형 삽화 감지 ({largest_blob_ratio*100:.2f}%)", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    if not has_substantive_text and not is_thin_text_strip and ink_ratio >= th["ink"] and midtone_ratio >= th["mid"]:
        return True, "흑백 삽화/음영 밀도 높음", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio
    return False, "텍스트 추정", color_ratio, ink_ratio, largest_blob_ratio, midtone_ratio


def fast_find_vertical_split(
    img: Image.Image,
    read_direction: str = "RTL",
) -> Optional[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]]:
    w, h = img.size
    if w < 120 or h < 120:
        return None
    rgb = ensure_rgb(img)
    rtl = 1 if read_direction.upper() == "RTL" else 0
    if c_layout is not None:
        try:
            return c_layout.find_vertical_split(rgb.tobytes(), w, h, rtl)
        except Exception:
            pass
    return None
