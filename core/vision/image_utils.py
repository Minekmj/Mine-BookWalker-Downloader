import threading
import hashlib
import re
import zlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageOps

from core.vision.fast_detector import (
    fast_detect_illustration_bounds,
    fast_has_center_gutter,
    fast_is_blank,
    fast_trim_bounds,
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def natural_sort_key(text: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def list_images_in_folder(folder: Path) -> List[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    files.sort(key=lambda p: natural_sort_key(p.name))
    return files


def load_image_rgb(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return im.convert("RGB")


def save_tmp_image(img: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    rgb.save(tmp, format="PNG", compress_level=1)
    try:
        tmp.replace(path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        if not path.exists():
            raise
    return path


def load_entry_image(entry: Dict) -> Optional[Image.Image]:
    img = entry.get("image")
    if img is not None:
        return img
    p = entry.get("image_path")
    if p:
        path = Path(p)
        if path.is_file():
            return load_image_rgb(path)
    return None


def get_image_size(entry: Dict) -> Tuple[int, int]:
    img = entry.get("image")
    if img is not None:
        return img.size
    sz = entry.get("image_size")
    if sz and len(sz) == 2:
        return (int(sz[0]), int(sz[1]))
    p = entry.get("image_path")
    if p:
        path = Path(p)
        if path.is_file():
            with Image.open(path) as im:
                return im.size
    return (0, 0)


def pack_image_rgb(img: Image.Image) -> Tuple[int, int, bytes]:
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    return (rgb.width, rgb.height, zlib.compress(rgb.tobytes(), level=1))


def unpack_image_rgb(packed: Tuple[int, int, bytes]) -> Image.Image:
    w, h, data = packed
    return Image.frombytes("RGB", (w, h), zlib.decompress(data))


def split_image_pages(
    img: Image.Image,
    direction: str = "RTL",
    only_if_wide: bool = True,
) -> List[Image.Image]:
    w, h = img.size
    if only_if_wide and w <= h:
        return [img]
    if w < 20:
        return [img]

    mid = w // 2
    left = img.crop((0, 0, mid, h))
    right = img.crop((mid, 0, w, h))

    if direction.upper() == "RTL":
        return [right, left]
    return [left, right]


def has_center_gutter(img: Image.Image, white_threshold: int = 235) -> bool:
    return fast_has_center_gutter(img, white_threshold=white_threshold)


def trim_white_margins(
    img: Image.Image,
    trim_top: bool = True,
    trim_bottom: bool = True,
    trim_left: bool = True,
    trim_right: bool = True,
    white_threshold: int = 240,
    noise_ratio: float = 0.0015,
    padding: int = 1,
) -> Image.Image:
    w, h = img.size
    if h < 10 or w < 10:
        return img
    bx1, by1, bx2, by2 = fast_trim_bounds(img, white_threshold=white_threshold, noise_ratio=noise_ratio, padding=padding)
    x1 = bx1 if trim_left else 0
    y1 = by1 if trim_top else 0
    x2 = bx2 if trim_right else w
    y2 = by2 if trim_bottom else h
    if x1 == 0 and y1 == 0 and x2 == w and y2 == h:
        return img
    if x2 - x1 < 10 or y2 - y1 < 10:
        return img
    return img.crop((x1, y1, x2, y2))


def crop_top_bottom_pct(
    img: Image.Image,
    top_pct: float = 3.0,
    footer_bottom_pct: float = 0.0,
) -> Image.Image:
    if top_pct <= 0:
        return img
    w, h = img.size
    y1 = int(round(h * max(0.0, top_pct) / 100.0))
    if h - y1 < 10:
        return img
    return img.crop((0, y1, w, h))


def is_blank_image(img: Image.Image, white_threshold: int = 248) -> bool:
    if white_threshold == 248:
        cached = getattr(img, "_cached_is_blank", None)
        if cached is not None:
            return cached
    result = fast_is_blank(img, white_threshold=white_threshold)
    if white_threshold == 248:
        try:
            setattr(img, "_cached_is_blank", result)
        except Exception:
            pass
    return result


def image_fingerprint(img: Image.Image) -> str:
    cached = getattr(img, "_cached_fingerprint", None)
    if cached is not None:
        return cached
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    digest = hashlib.blake2b(digest_size=16)
    digest.update(f"{rgb.width}x{rgb.height}:".encode("ascii"))
    digest.update(rgb.tobytes())
    value = digest.hexdigest()
    try:
        setattr(img, "_cached_fingerprint", value)
    except Exception:
        pass
    return value


def crop_normalized_rect(img: Image.Image, rect) -> Image.Image:
    if not rect or len(rect) != 4:
        return img
    x, y, width, height = [float(value) for value in rect]
    x1 = max(0, min(img.width - 1, int(round(x * img.width))))
    y1 = max(0, min(img.height - 1, int(round(y * img.height))))
    x2 = max(x1 + 1, min(img.width, int(round((x + width) * img.width))))
    y2 = max(y1 + 1, min(img.height, int(round((y + height) * img.height))))
    if x2 - x1 < 10 or y2 - y1 < 10:
        return img
    return img.crop((x1, y1, x2, y2))


def detect_illustration_bounds(img: Image.Image, padding_ratio: float = 0.006):
    return fast_detect_illustration_bounds(img, padding_ratio=padding_ratio)


def crop_illustration_bounds(img: Image.Image, padding_ratio: float = 0.006) -> Image.Image:
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    bounds = detect_illustration_bounds(rgb, padding_ratio)
    return rgb.crop(bounds) if bounds != (0, 0, rgb.width, rgb.height) else rgb