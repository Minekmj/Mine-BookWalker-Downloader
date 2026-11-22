from PIL import Image

try:
    from C import c_margins
except Exception:
    c_margins = None

try:
    from C import c_header
except Exception:
    c_header = None

try:
    from C import c_layout
except Exception:
    c_layout = None

try:
    from C import c_illust
except Exception:
    c_illust = None


def ensure_rgb(img: Image.Image) -> Image.Image:
    return img if img.mode == "RGB" else img.convert("RGB")
