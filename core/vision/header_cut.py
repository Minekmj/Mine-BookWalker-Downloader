from PIL import Image

from core.vision.fast_detector import fast_detect_header_cut
from core.vision.image_utils import crop_top_bottom_pct

HEADER_CUT_MODES = ("auto", "always", "off")


def cut_header(img: Image.Image, top_pct: float, mode: str, is_illustration: bool) -> Image.Image:
    if mode == "off" or top_pct <= 0:
        return img
    if mode == "always":
        return crop_top_bottom_pct(img, top_pct)
    if not is_illustration:
        return crop_top_bottom_pct(img, top_pct)
    cut_y = fast_detect_header_cut(img, top_pct)
    if cut_y > 0 and img.height - cut_y >= 10:
        return img.crop((0, cut_y, img.width, img.height))
    return img