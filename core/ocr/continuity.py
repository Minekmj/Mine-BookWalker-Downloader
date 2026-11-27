from typing import Dict, List

from core.ocr.models import OCRParagraph
from core.ocr.rules import is_scene_break_text


_HARD_ENDINGS = ("。", "！", "？", "!", "?", "」", "』", "】", "）", ")", "…", "……")


def _can_join(previous: OCRParagraph, following: OCRParagraph) -> bool:
    if previous.is_scene_break or following.is_scene_break:
        return False
    if previous.is_heading or following.is_heading or previous.is_toc_entry or following.is_toc_entry:
        return False
    if previous.block_type in {"toc_title", "chapter_heading", "section_heading", "divider", "scene_break", "toc_entry"}:
        return False
    if following.block_type in {"toc_title", "chapter_heading", "section_heading", "divider", "scene_break", "toc_entry"}:
        return False
    left = previous.plain_text.rstrip()
    right = following.plain_text.lstrip()
    if not left or not right:
        return False
    if previous.ends_open:
        return True
    if left.endswith(_HARD_ENDINGS):
        return False
    if right.startswith(("「", "『", "【", "◆", "◇", "＊", "*", "※")):
        return False
    return True


def _merge_pair(left: OCRParagraph, right: OCRParagraph) -> None:
    left.spans.extend(right.spans)
    left.ends_open = bool(right.ends_open)


def merge_page_continuations(entries: List[Dict]) -> List[Dict]:
    ordered = sorted(entries, key=lambda item: int(item.get("page_no", 0)))
    for entry in ordered:
        if entry.get("type") != "text":
            continue
        paragraphs = entry.get("paragraphs", [])
        for paragraph in paragraphs:
            actual_scene_break = is_scene_break_text(paragraph.plain_text)
            paragraph.is_scene_break = actual_scene_break
            if paragraph.block_type in {"divider", "scene_break"} and not actual_scene_break:
                paragraph.block_type = "paragraph"
                paragraph.is_heading = False
                paragraph.heading_level = 0
        index = 0
        while index + 1 < len(paragraphs):
            if _can_join(paragraphs[index], paragraphs[index + 1]):
                _merge_pair(paragraphs[index], paragraphs[index + 1])
                paragraphs.pop(index + 1)
            else:
                index += 1
        for index, paragraph in enumerate(paragraphs):
            paragraph.reading_order = index
    previous_entry = None
    for entry in ordered:
        if entry.get("type") != "text" or previous_entry is None or previous_entry.get("type") != "text":
            previous_entry = entry
            continue
        if int(entry.get("page_no", 0)) != int(previous_entry.get("page_no", 0)) + 1:
            previous_entry = entry
            continue
        previous_paragraphs = previous_entry.get("paragraphs", [])
        current_paragraphs = entry.get("paragraphs", [])
        if not previous_paragraphs or not current_paragraphs:
            previous_entry = entry
            continue
        left = previous_paragraphs[-1]
        right = current_paragraphs[0]
        if _can_join(left, right):
            _merge_pair(left, right)
            current_paragraphs.pop(0)
            left.reading_order = max(0, int(left.reading_order))
            for index, paragraph in enumerate(current_paragraphs):
                paragraph.reading_order = index
        previous_entry = entry
    return ordered
