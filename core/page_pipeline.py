from typing import List, Optional

from PIL import Image

from core.header_cut import cut_header
from core.image_utils import crop_illustration_bounds, trim_white_margins
from core.novel_detector import SplitPart, resolve_split_pages
from core.part_splitter import auto_separate_parts


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
        )
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