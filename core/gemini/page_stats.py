from typing import Dict, List, Tuple

import numpy as np
from PIL import Image

from core.epub import is_chapter_heading
from core.gemini.markup import _has_repetition_loop
from core.ocr_engine import OCRParagraph


def compute_page_ink_ratio(img: Image.Image) -> float:
    small = img.convert("L").resize((256, 256), Image.Resampling.BILINEAR)
    arr = np.asarray(small)
    return float(np.mean(arr < 200))


def compute_page_zscores(records: List[Dict], z_threshold: float = 2.5) -> Tuple[List[Dict], Dict]:
    valid_items = [
        r for r in records
        if not r.get("is_illustration_only") and not r.get("is_heading_only")
    ]
    if len(valid_items) < 5:
        for r in records:
            r["z_score"] = 0.0
            r["expected_chars"] = r.get("char_count", 0)
            r["z_anomaly"] = False
        return records, {"count": len(valid_items), "mean_err": 0.0, "std_err": 0.0}

    xs = np.array([r["ink_ratio"] for r in valid_items], dtype=np.float64)
    ys = np.array([r["char_count"] for r in valid_items], dtype=np.float64)

    mean_x = float(np.mean(xs))
    mean_y = float(np.mean(ys))
    var_x = float(np.sum((xs - mean_x) ** 2))

    if var_x > 1e-9:
        a = float(np.sum((xs - mean_x) * (ys - mean_y)) / var_x)
        if a < 0:
            a = 0.0
            b = mean_y
        else:
            b = mean_y - a * mean_x
    else:
        a = 0.0
        b = mean_y

    errs = ys - (a * xs + b)
    mean_err = float(np.mean(errs))
    std_err = float(np.std(errs))

    for r in records:
        if r.get("is_illustration_only") or r.get("is_heading_only"):
            r["z_score"] = 0.0
            r["expected_chars"] = r.get("char_count", 0)
            r["z_anomaly"] = False
            continue

        pred = max(0.0, a * r["ink_ratio"] + b)
        err = r["char_count"] - pred
        z = ((err - mean_err) / std_err) if std_err > 1e-6 else 0.0
        r["expected_chars"] = round(pred, 1)
        r["z_score"] = round(z, 2)
        r["z_anomaly"] = (abs(z) > z_threshold) or r["char_count"] == 0 or r.get("has_loop", False)

    return records, {"count": len(valid_items), "mean_err": mean_err, "std_err": std_err}


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
