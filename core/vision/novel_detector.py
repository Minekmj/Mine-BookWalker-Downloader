from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image

from core.vision.fast_detector import fast_analyze_page, fast_detect_header_cut, fast_trim_bounds
from core.vision.image_utils import (
    crop_top_bottom_pct,
    has_center_gutter,
    is_blank_image,
    split_image_pages,
)


@dataclass
class PageAnalysis:
    is_illustration: bool
    reason: str
    color_ratio: float
    ink_ratio: float
    largest_blob_ratio: float
    midtone_ratio: float


@dataclass
class SplitPart:
    image: Optional[Image.Image]
    split_note: str
    is_illustration: bool
    analysis_reason: str
    header_cut_applied: bool = False
    detected_header_cut_y: int = -1
    is_mini_illust: bool = False
    image_path: Optional[Path] = None
    fingerprint: str = ""
    is_blank: Optional[bool] = None


def analyze_novel_page(
    img: Image.Image,
    sensitivity: str = "normal",
    small_illust: bool = False,
    orig_size: Optional[Tuple[int, int]] = None,
) -> PageAnalysis:
    is_ill, reason, col_r, ink_r, blob_r, mid_r = fast_analyze_page(
        img,
        sensitivity=sensitivity,
        small_illust=small_illust,
        orig_size=orig_size,
    )
    return PageAnalysis(is_ill, reason, col_r, ink_r, blob_r, mid_r)


def resolve_split_pages(
    img: Image.Image,
    is_first_file: bool,
    mode: str,
    split_enabled: bool,
    split_skip_first: bool,
    split_only_wide: bool,
    split_large_images: bool,
    read_direction: str,
    illust_sensitivity: str = "normal",
    remove_text_header: bool = True,
    header_top_pct: float = 3.0,
    footer_bottom_pct: float = 0.0,
    header_cut_mode: str = "auto",
    small_illust_enabled: bool = True,
    trim_before_illust_detect: bool = True,
    white_threshold: int = 240,
) -> List[SplitPart]:
    def analyze_single(part_img: Image.Image, is_first: bool) -> SplitPart:
        if is_blank_image(part_img):
            return SplitPart(part_img, "빈 페이지", False, "빈 페이지", detected_header_cut_y=0)
        if mode == "manga":
            return SplitPart(part_img, "만화 이미지", True, "만화 페이지", detected_header_cut_y=0)

        check_img = part_img
        detected_cut_y = 0
        if not is_first and remove_text_header and header_cut_mode != "off" and header_top_pct > 0:
            if header_cut_mode == "always":
                check_img = crop_top_bottom_pct(part_img, header_top_pct)
                detected_cut_y = max(0, part_img.height - check_img.height)
            else:
                cut_y = fast_detect_header_cut(part_img, header_top_pct)
                detected_cut_y = cut_y
                if cut_y > 0 and part_img.height - cut_y >= 10:
                    check_img = part_img.crop((0, cut_y, part_img.width, part_img.height))

        if is_blank_image(check_img):
            return SplitPart(part_img, "빈 페이지", False, "빈 페이지", detected_header_cut_y=detected_cut_y)

        orig_sz = check_img.size
        trimmed_sz = orig_sz
        if trim_before_illust_detect:
            bx1, by1, bx2, by2 = fast_trim_bounds(check_img, white_threshold=white_threshold)
            if (bx1, by1, bx2, by2) != (0, 0, check_img.width, check_img.height):
                check_img = check_img.crop((bx1, by1, bx2, by2))
                trimmed_sz = check_img.size

        a = analyze_novel_page(
            check_img,
            sensitivity=illust_sensitivity,
            small_illust=small_illust_enabled,
            orig_size=orig_sz,
        )
        is_mini = False
        if a.is_illustration and not is_first:
            orig_area = max(1, orig_sz[0] * orig_sz[1])
            trim_area = trimmed_sz[0] * trimmed_sz[1]
            if "단독 소형 삽화" in a.reason or (trim_before_illust_detect and trim_area < orig_area * 0.25):
                is_mini = True
        return SplitPart(
            part_img,
            "단면 이미지" if is_first else "분할 페이지",
            a.is_illustration,
            a.reason,
            header_cut_applied=False,
            detected_header_cut_y=detected_cut_y if not is_first else -1,
            is_mini_illust=is_mini,
        )

    if not split_enabled or (split_skip_first and is_first_file):
        return [analyze_single(img, is_first_file)]

    w, h = img.size
    should_split = False
    pre_halves = None
    if w > h:
        if split_large_images:
            should_split = True
        elif has_center_gutter(img, white_threshold=white_threshold):
            if mode == "manga":
                should_split = True
            else:
                pre_halves = split_image_pages(img, direction=read_direction, only_if_wide=False)
                if not all(
                    analyze_novel_page(hf, sensitivity=illust_sensitivity, small_illust=False).is_illustration
                    for hf in pre_halves
                ):
                    should_split = True
    elif not split_only_wide:
        if split_large_images and w >= 1200:
            should_split = True
        elif has_center_gutter(img, white_threshold=white_threshold):
            if mode == "manga":
                should_split = True
            else:
                pre_halves = split_image_pages(img, direction=read_direction, only_if_wide=False)
                if not all(
                    analyze_novel_page(hf, sensitivity=illust_sensitivity, small_illust=False).is_illustration
                    for hf in pre_halves
                ):
                    should_split = True

    if not should_split:
        return [analyze_single(img, is_first_file)]

    halves = pre_halves or split_image_pages(img, direction=read_direction, only_if_wide=False)
    results = []
    for half in halves:
        part = analyze_single(half, False)
        part.split_note = "양면 분할"
        results.append(part)
    return results