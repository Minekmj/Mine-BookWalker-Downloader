from core.vision.fast_detector.illust import fast_detect_illustration_bounds
from core.vision.fast_detector.layout import fast_analyze_page, fast_find_vertical_split
from core.vision.fast_detector.margins import (
    fast_detect_header_cut,
    fast_has_center_gutter,
    fast_is_blank,
    fast_trim_bounds,
)

__all__ = [
    "fast_analyze_page",
    "fast_detect_header_cut",
    "fast_detect_illustration_bounds",
    "fast_find_vertical_split",
    "fast_has_center_gutter",
    "fast_is_blank",
    "fast_trim_bounds",
]
