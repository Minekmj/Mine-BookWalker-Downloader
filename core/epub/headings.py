import re
from typing import List

from core.epub.patterns import CHAPTER_PATTERNS, PAGE_SUFFIX_RE, SECTION_PATTERNS, SYMBOL_CHAPTER_RE, TOC_TITLE_RE
from core.epub.text_utils import _clean_ruby
from core.ocr_engine import OCRParagraph

_TOC_DECOR_RE = re.compile(r"[\s\u3000◆◇■□●○◎★☆・\-－―─━┃:.：\[\]【】()（）「」『』]+")


def is_toc_title_text(text: str) -> bool:
    cleaned = _TOC_DECOR_RE.sub("", text or "")
    return bool(cleaned and TOC_TITLE_RE.match(cleaned))


def is_toc_like_line(para: OCRParagraph) -> bool:
    if para.is_scene_break:
        return False
    text = _clean_ruby(para.plain_text).strip()
    if not text or len(text) > 55:
        return False
    if text.startswith(("「", "『", "（", "(")) or text.endswith(("。", "、", "」", "』")):
        return False
    if para.is_toc_entry or para.block_type in {"toc_entry", "toc_title"} or PAGE_SUFFIX_RE.search(text):
        return True
    if para.is_heading or para.is_toc_candidate or para.is_all_bold:
        return True
    if SYMBOL_CHAPTER_RE.match(text):
        return True
    if any(pattern.match(text) for pattern in CHAPTER_PATTERNS) or any(pattern.match(text) for pattern in SECTION_PATTERNS):
        return True
    return False


def is_chapter_heading(para: OCRParagraph) -> bool:
    if para.is_scene_break or para.is_toc_entry:
        return False
    text = _clean_ruby(para.plain_text).strip()
    if not text or len(text) > 70 or text.startswith(("「", "『", "【", "（", "(")) or text.endswith(("。", "、", "」", "』")):
        return False
    if para.block_type == "chapter_heading":
        return True
    if any(pattern.match(text) for pattern in SECTION_PATTERNS):
        return False
    if any(pattern.match(text) for pattern in CHAPTER_PATTERNS):
        return True
    if SYMBOL_CHAPTER_RE.match(text) and (para.is_heading or para.is_all_bold):
        return True
    if para.block_type in {"section_heading", "subheading"} or para.heading_level >= 2:
        return False
    return bool(para.is_heading and para.heading_level in (0, 1))


def is_section_heading(para: OCRParagraph) -> bool:
    if para.is_scene_break or para.is_toc_entry or para.block_type in {"toc_title", "toc_entry"} or is_chapter_heading(para):
        return False
    text = _clean_ruby(para.plain_text).strip()
    if not text or len(text) > 80 or text.endswith(("。", "、", "」", "』")):
        return False
    if para.block_type in {"section_heading", "subheading"}:
        return True
    if para.is_heading and para.heading_level >= 2:
        return True
    if any(pattern.match(text) for pattern in SECTION_PATTERNS):
        return True
    return bool(para.is_all_bold and len(text) <= 45)


def is_printed_toc_page(paragraphs: List[OCRParagraph]) -> bool:
    visible = [paragraph for paragraph in paragraphs if paragraph.plain_text.strip()]
    if not visible:
        return False
    if any(is_toc_title_text(_clean_ruby(paragraph.plain_text)) or paragraph.block_type == "toc_title" for paragraph in visible[:4]):
        return True
    marked_rows = sum(1 for paragraph in visible if paragraph.is_toc_entry or paragraph.block_type == "toc_entry")
    if marked_rows >= 2:
        return True
    visual_rows = sum(1 for paragraph in visible if PAGE_SUFFIX_RE.search(_clean_ruby(paragraph.plain_text).strip()))
    if visual_rows >= 2 and len(visible) <= visual_rows + 3:
        return True
    non_break = [p for p in visible if not p.is_scene_break]
    if len(non_break) >= 3:
        has_narrative = any(
            len(_clean_ruby(p.plain_text).strip()) > 65 or _clean_ruby(p.plain_text).strip().endswith("。")
            for p in non_break
        )
        if not has_narrative:
            toc_like = sum(1 for p in non_break if is_toc_like_line(p))
            if toc_like >= max(3, int(len(non_break) * 0.7)):
                return True
    return False