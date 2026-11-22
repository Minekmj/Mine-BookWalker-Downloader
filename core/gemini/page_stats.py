from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

from core.export.epub import is_chapter_heading
from core.gemini.markup import _has_repetition_loop
from core.ocr import OCRParagraph


def compute_page_ink_ratio(img: Image.Image) -> float:
    small = img.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=np.float32)
    core = arr[10:-10, 10:-10]
    paper = float(np.percentile(core, 85))
    thresh = min(210.0, max(120.0, paper - 35.0))
    return float(np.mean(core < thresh))


def _fit_weighted_line(xs: np.ndarray, ys: np.ndarray, weights: np.ndarray) -> Tuple[float, float]:
    w_sum = float(np.sum(weights))
    if w_sum <= 1e-9:
        return 0.0, float(np.median(ys))
    mean_x = float(np.sum(weights * xs) / w_sum)
    mean_y = float(np.sum(weights * ys) / w_sum)
    var_x = float(np.sum(weights * (xs - mean_x) ** 2))
    if var_x <= 1e-9:
        return 0.0, mean_y
    a = float(np.sum(weights * (xs - mean_x) * (ys - mean_y)) / var_x)
    if a < 0.0:
        return 0.0, mean_y
    return a, mean_y - a * mean_x


def compute_page_zscores(records: List[Dict], z_threshold: float = 2.5) -> Tuple[List[Dict], Dict]:
    valid_items = [
        r for r in records
        if not r.get("is_illustration_only") and not r.get("is_heading_only")
    ]
    fit_items = [
        r for r in valid_items
        if r.get("char_count", 0) > 0 and not r.get("has_loop", False)
    ]
    if len(fit_items) < 5:
        for r in records:
            is_fail = (not r.get("is_illustration_only") and not r.get("is_heading_only")) and (
                r.get("char_count", 0) == 0 or r.get("has_loop", False)
            )
            r["z_score"] = 0.0
            r["expected_chars"] = r.get("char_count", 0)
            r["z_anomaly"] = is_fail
        return records, {"count": len(fit_items), "mean_err": 0.0, "std_err": 0.0}

    xs = np.array([r["ink_ratio"] for r in fit_items], dtype=np.float64)
    ys = np.array([r["char_count"] for r in fit_items], dtype=np.float64)

    weights = np.ones_like(xs)
    a, b = _fit_weighted_line(xs, ys, weights)
    for _ in range(3):
        errs_fit = ys - np.maximum(0.0, a * xs + b)
        med = float(np.median(errs_fit))
        mad = float(np.median(np.abs(errs_fit - med)))
        scale = max(1.4826 * mad, 20.0)
        abs_r = np.abs(errs_fit - med)
        huber_k = 1.5 * scale
        weights = np.where(abs_r <= huber_k, 1.0, huber_k / np.maximum(abs_r, 1e-6))
        a, b = _fit_weighted_line(xs, ys, weights)

    errs_fit = ys - np.maximum(0.0, a * xs + b)
    med_err = float(np.median(errs_fit))
    mad = float(np.median(np.abs(errs_fit - med_err)))
    robust_std = 1.4826 * mad
    if robust_std < 15.0:
        q75, q25 = np.percentile(errs_fit, [75, 25])
        iqr_std = float((q75 - q25) / 1.349)
        trimmed = errs_fit[np.abs(errs_fit - med_err) <= max(3.0 * iqr_std, 40.0)]
        trim_std = float(np.std(trimmed)) if len(trimmed) >= 3 else float(np.std(errs_fit))
        robust_std = max(robust_std, iqr_std, trim_std, 15.0)

    for r in records:
        if r.get("is_illustration_only") or r.get("is_heading_only"):
            r["z_score"] = 0.0
            r["expected_chars"] = r.get("char_count", 0)
            r["z_anomaly"] = False
            continue

        pred = max(0.0, a * r["ink_ratio"] + b)
        err = r["char_count"] - pred
        z = (err - med_err) / robust_std
        r["expected_chars"] = round(pred, 1)
        r["z_score"] = round(z, 2)
        significant_gap = abs(err - med_err) >= 20.0
        r["z_anomaly"] = (abs(z) > z_threshold and significant_gap) or r["char_count"] == 0 or r.get("has_loop", False)

    return records, {"count": len(fit_items), "mean_err": med_err, "std_err": robust_std}


def summarize_page_for_zscore(page_no: int, img: Image.Image, paragraphs: List[OCRParagraph], is_ill: bool) -> Dict:
    plain = "".join(p.plain_text for p in paragraphs)
    clean_chars = len("".join(plain.split()))
    non_empty = [p for p in paragraphs if p.plain_text.strip() and not p.is_scene_break]
    is_heading_only = bool(non_empty) and len(non_empty) <= 2 and all(is_chapter_heading(p) for p in non_empty)
    return {
        "page_no": page_no,
        "ink_ratio": compute_page_ink_ratio(img),
        "char_count": clean_chars,
        "is_illustration_only": is_ill,
        "is_heading_only": is_heading_only,
        "has_loop": _has_repetition_loop(plain),
    }
