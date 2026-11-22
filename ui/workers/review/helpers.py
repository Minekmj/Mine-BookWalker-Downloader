from difflib import SequenceMatcher
import re

from PIL import Image, ImageDraw, ImageFont

from core.export.epub.chapters import _ordered_paragraphs
from core.export.epub.text_utils import _clean_ruby
from core.vision.image_utils import load_entry_image


def strip_for_diff(text: str) -> str:
    return "".join(re.sub(r"</?(?:b|title|bic|ft)\b[^>]*>", "", text or "", flags=re.IGNORECASE).split())


def is_safe_content_correction(old_text: str, new_text: str) -> bool:
    old_plain = strip_for_diff(old_text)
    new_plain = strip_for_diff(new_text)
    if not old_plain or not new_plain:
        return False
    if old_plain == new_plain:
        return True
    old_len, new_len = len(old_plain), len(new_plain)
    if old_len >= 40 and new_len < old_len * 0.65:
        return False
    if abs(new_len - old_len) > max(20, int(old_len * 0.25)):
        return False
    if SequenceMatcher(None, old_plain, new_plain).ratio() < 0.72:
        return False
    return True


class ReviewHelpersMixin:
    def _make_illustration_contact_sheet(self, entries, original_loader):
        illustrations = [
            entry for entry in sorted(entries, key=lambda value: int(value.get("page_no", 0)))
            if entry.get("type") == "illustration" and (entry.get("image") is not None or entry.get("image_path"))
        ]
        if not illustrations:
            return None
        thumb_width, thumb_height = 72, 92
        pair_gap, cell_gap, label_height = 8, 8, 18
        columns = min(20, max(4, int((len(illustrations) * 1.5) ** 0.5 + 0.5)))
        cell_width = thumb_width * 2 + pair_gap
        cell_height = thumb_height + label_height + 8
        rows = (len(illustrations) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_width + (columns + 1) * cell_gap, rows * cell_height + (rows + 1) * cell_gap), "white")
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.load_default(size=12)
        except TypeError:
            font = ImageFont.load_default()
        for index, entry in enumerate(illustrations):
            column, row = index % columns, index // columns
            x = cell_gap + column * (cell_width + cell_gap)
            y = cell_gap + row * (cell_height + cell_gap)
            page_no = int(entry["page_no"])
            draw.text((x, y), f"ILLUST {index + 1} / PAGE {page_no}", fill="black", font=font)
            orig_img = original_loader(page_no)
            cropped_img = load_entry_image(entry)
            for offset, label, image in ((0, "ORIGINAL", orig_img), (thumb_width + pair_gap, "CROPPED", cropped_img)):
                draw.text((x + offset, y + label_height), label, fill=(50, 50, 50), font=font)
                if image is None:
                    continue
                thumb = image.convert("RGB")
                thumb.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
                px = x + offset + (thumb_width - thumb.width) // 2
                py = y + label_height + 6 + (thumb_height - thumb.height) // 2
                sheet.paste(thumb, (px, py))
                draw.rectangle((x + offset, y + label_height + 6, x + offset + thumb_width - 1, y + label_height + thumb_height + 5), outline=(130, 130, 130))
        return sheet

    def _collect_context_window(self, flat_paras, center_pos: int, direction: int, limit_chars: int = 180) -> str:
        collected = []
        total_len = 0
        pos = center_pos + direction
        steps = 0
        while 0 <= pos < len(flat_paras) and steps < 4 and total_len < limit_chars:
            _, _, p, is_toc = flat_paras[pos]
            if not is_toc and not p.is_scene_break and not p.is_toc_entry:
                t = _clean_ruby(p.plain_text).strip()
                if t:
                    collected.append(t[:100])
                    total_len += len(t)
                    steps += 1
            pos += direction
        if direction < 0:
            collected.reverse()
        return " / ".join(collected)

    def _page_text_snippet(self, entry: dict, from_end: bool) -> str:
        paras = _ordered_paragraphs(entry.get("paragraphs", []))
        lines = [_clean_ruby(pr.plain_text).strip() for pr in paras if not pr.is_scene_break and _clean_ruby(pr.plain_text).strip()]
        if not lines:
            return ""
        picked = lines[-3:] if from_end else lines[:3]
        return " / ".join(t[:90] for t in picked)
