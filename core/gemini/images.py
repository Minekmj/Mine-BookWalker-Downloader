import io

from PIL import Image, ImageDraw, ImageFont


def _make_labeled_png_bytes(img: Image.Image, seq_idx: int, page_no: int) -> bytes:

    banner_h = 28
    w, h = img.size
    canvas = Image.new("RGB", (w, h + banner_h), (255, 255, 255))
    canvas.paste(img, (0, banner_h))

    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, w, banner_h - 1], fill=(240, 244, 248))
    draw.line([(0, banner_h - 1), (w, banner_h - 1)], fill=(120, 130, 145), width=1)
    label = f"IMAGE {seq_idx}  |  page_no={page_no}"
    try:
        font = ImageFont.load_default(size=16)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((10, 5), label, fill=(20, 25, 35), font=font)

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()
