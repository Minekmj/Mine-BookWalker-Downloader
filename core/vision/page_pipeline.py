from typing import List, Optional, Tuple

from PIL import Image

from core.vision.header_cut import cut_header
from core.vision.image_utils import crop_illustration_bounds, crop_side_pct, trim_white_margins
from core.vision.novel_detector import SplitPart, resolve_split_pages
from core.vision.part_splitter import auto_separate_parts


def compute_base_parts(img: Image.Image, is_first_file: bool, is_novel: bool, params: dict) -> List[SplitPart]:
    mode = "novel" if is_novel else "manga"
    parts = resolve_split_pages(
        img=img,
        is_first_file=is_first_file,
        mode=mode,
        split_enabled=params["split_enabled"],
        split_skip_first=params["split_skip_first"],
        split_only_wide=params["split_only_wide"],
        split_large_images=params["split_large_images"],
        read_direction=params["read_direction"],
        illust_sensitivity=params["illust_sensitivity"],
        remove_text_header=is_novel and params["remove_text_header"],
        header_top_pct=params["header_top_pct"],
        footer_bottom_pct=params["footer_bottom_pct"],
        header_cut_mode=params.get("header_cut_mode", "auto"),
        small_illust_enabled=params.get("small_illust_enabled", True),
        trim_before_illust_detect=params.get("trim_before_illust_detect", True),
        white_threshold=params.get("white_threshold", 240),
    )
    if not params["split_enabled"] or (params["split_skip_first"] and is_first_file):
        return parts
    if params.get("auto_separate_disabled", False):
        return parts
    return auto_separate_parts(
        parts,
        mode,
        params["read_direction"],
        params["illust_sensitivity"],
        small_illust=params.get("small_illust_enabled", True),
        remove_text_header=is_novel and params["remove_text_header"],
        header_top_pct=params["header_top_pct"],
        header_cut_mode=params.get("header_cut_mode", "auto"),
        trim_before_illust_detect=params.get("trim_before_illust_detect", True),
        white_threshold=params.get("white_threshold", 240),
        split_large_images=bool(params.get("split_large_images", False)),
    )


def default_illust_trim_enabled(part: SplitPart, params: dict) -> bool:
    if getattr(part, "is_mini_illust", False):
        return False
    return bool(params.get("trim_enabled", True))


def render_illustration_image(
    part: SplitPart,
    params: dict,
    trim_override: Optional[bool] = None,
    side_crop: Optional[Tuple[float, float]] = None,
) -> Image.Image:
    image = part.image.convert("RGB")
    if params.get("crop_illustrations", False) and params.get("remove_text_header", True) and not part.header_cut_applied:
        image = cut_header(
            image,
            float(params.get("header_top_pct", 3.0)),
            str(params.get("header_cut_mode", "auto")),
            True,
        )
    should_trim = default_illust_trim_enabled(part, params) if trim_override is None else bool(trim_override)
    if should_trim:
        image = crop_illustration_bounds(image)
        image = trim_white_margins(
            image,
            trim_top=bool(params.get("trim_top", True)),
            trim_bottom=bool(params.get("trim_bottom", True)),
            trim_left=bool(params.get("trim_left", True)),
            trim_right=bool(params.get("trim_right", True)),
            white_threshold=int(params.get("white_threshold", 240)),
            padding=int(params.get("trim_padding", 1)),
            extra_px=int(params.get("trim_extra_px", 0)),
        )
    if side_crop and len(side_crop) == 2:
        image = crop_side_pct(image, float(side_crop[0]), float(side_crop[1]))
    return image


def prepare_text_ocr_image(part: SplitPart, params: dict) -> Image.Image:
    if part.header_cut_applied:
        return part.image
    if not params.get("remove_text_header", True):
        return part.image
    mode = str(params.get("header_cut_mode", "auto"))
    if mode == "off":
        return part.image
    return cut_header(
        part.image,
        float(params.get("header_top_pct", 3.0)),
        mode,
        False,
    )
def split_illustration_side_crop(
    part: SplitPart,
    side_crop: Optional[Tuple[float, float]] = None,
    origin_key: str = "",
) -> List[SplitPart]:
    if not side_crop or len(side_crop) != 2 or part.image is None:
        return [part]
    lp = max(0.0, min(49.0, float(side_crop[0])))
    rp = max(0.0, min(49.0, float(side_crop[1])))
    if lp <= 0.0 and rp <= 0.0:
        return [part]

    base_img = part.image.convert("RGB")
    w, h = base_img.size
    x1 = int(round(w * lp / 100.0))
    x2 = w - int(round(w * rp / 100.0))
    if x2 - x1 < 10:
        return [part]

    result: List[SplitPart] = []
    if rp > 0.0 and w - x2 >= 5:
        right_img = base_img.crop((x2, 0, w, h))
        result.append(
            SplitPart(
                right_img,
                "삽화 우측 본문 분리",
                False,
                "삽화에서 분리된 본문 (이전 페이지)",
                header_cut_applied=part.header_cut_applied,
                side_crop_origin_key=origin_key,
            )
        )

    mid_img = base_img.crop((x1, 0, x2, h))
    result.append(
        SplitPart(
            mid_img,
            part.split_note,
            True,
            part.analysis_reason,
            header_cut_applied=part.header_cut_applied,
            detected_header_cut_y=part.detected_header_cut_y,
            is_mini_illust=part.is_mini_illust,
            side_crop_origin_key=origin_key,
        )
    )

    if lp > 0.0 and x1 >= 5:
        left_img = base_img.crop((0, 0, x1, h))
        result.append(
            SplitPart(
                left_img,
                "삽화 좌측 본문 분리",
                False,
                "삽화에서 분리된 본문 (다음 페이지)",
                header_cut_applied=part.header_cut_applied,
                side_crop_origin_key=origin_key,
            )
        )

    return result
