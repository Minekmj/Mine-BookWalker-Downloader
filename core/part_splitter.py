from typing import List

from core.fast_detector import fast_detect_header_cut, fast_find_vertical_split
from core.image_utils import crop_top_bottom_pct, is_blank_image
from core.novel_detector import SplitPart


def auto_separate_parts(
    parts: List[SplitPart],
    mode: str,
    read_direction: str,
    sensitivity: str = "normal",
    small_illust: bool = False,
    remove_text_header: bool = False,
    header_top_pct: float = 3.0,
    header_cut_mode: str = "auto",
    trim_before_illust_detect: bool = False,
    white_threshold: int = 240,
    split_large_images: bool = False,
) -> List[SplitPart]:
    if mode == "manga":
        return parts
    result: List[SplitPart] = []
    for part in parts:
        if is_blank_image(part.image):
            result.append(part)
            continue

        work_img = part.image
        cut_applied = part.header_cut_applied
        if remove_text_header and not cut_applied and header_cut_mode != "off" and header_top_pct > 0:
            if header_cut_mode == "always":
                cropped = crop_top_bottom_pct(part.image, header_top_pct)
                if cropped.size != part.image.size:
                    work_img = cropped
                    cut_applied = True
            else:
                cut_y = part.detected_header_cut_y if part.detected_header_cut_y >= 0 else fast_detect_header_cut(part.image, header_top_pct)
                if cut_y > 0 and part.image.height - cut_y >= 10:
                    work_img = part.image.crop((0, cut_y, part.image.width, part.image.height))
                    cut_applied = True

        separated = fast_find_vertical_split(work_img, read_direction=read_direction)
        if separated is None:
            result.append(part)
            continue

        ill_box, text_box = separated
        ill_img = part.image.crop((ill_box[0], 0, ill_box[2], part.image.height))
        text_img = part.image.crop((text_box[0], 0, text_box[2], part.image.height))

        ill_part = SplitPart(
            ill_img,
            "본문·삽화 분할: 삽화",
            True,
            "세로 경계면 기반 삽화 분리",
            header_cut_applied=False,
        )
        text_part = SplitPart(
            text_img,
            "본문·삽화 분할: 텍스트",
            False,
            "본문 텍스트",
            header_cut_applied=False,
        )

        if read_direction.upper() == "RTL":
            if ill_box[0] >= text_box[0]:
                result.append(ill_part)
                result.append(text_part)
            else:
                result.append(text_part)
                result.append(ill_part)
        else:
            if ill_box[0] <= text_box[0]:
                result.append(ill_part)
                result.append(text_part)
            else:
                result.append(text_part)
                result.append(ill_part)

    return result