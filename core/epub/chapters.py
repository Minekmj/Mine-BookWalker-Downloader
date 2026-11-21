import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.epub.headings import is_chapter_heading, is_printed_toc_page, is_section_heading
from core.epub.patterns import ROMAN_ALONE_RE, SYMBOL_CHAPTER_RE, TOC_TITLE_RE
from core.epub.text_utils import _clean_ruby, _copy_spans, _plain_key, _toc_text
from core.ocr_engine import OCRParagraph

PREFIX_STRIP_RE = re.compile(
    r"^(?:(?:[IVXLCDM]{1,7}|[Ⅰ-Ⅻⅰ-ⅻ]{1,4})\s*[・◆◇■□●○◎★☆\-－―─:.：]?\s*)?[◆◇■□●○◎★☆・\-－―─:.：\s]+"
)


@dataclass
class EpubChapter:
    title: str
    items: List[Dict] = field(default_factory=list)


def _ordered_paragraphs(paragraphs: List[OCRParagraph]) -> List[OCRParagraph]:
    indexed = list(enumerate(paragraphs))
    if any(paragraph.reading_order >= 0 for _, paragraph in indexed):
        indexed.sort(key=lambda pair: (pair[1].reading_order if pair[1].reading_order >= 0 else pair[0], pair[0]))
    return [paragraph for _, paragraph in indexed if paragraph.plain_text.strip()]


def deduplicate_entries(entries: List[Dict]) -> List[Dict]:
    indexed = sorted(enumerate(entries), key=lambda pair: (int(pair[1].get("page_no", pair[0] + 1)), pair[0]))
    result = []
    seen_page_numbers = set()
    seen_fingerprints = set()
    seen_source_keys = set()
    seen_text_hashes = set()
    for original_index, entry in indexed:
        page_no = int(entry.get("page_no", original_index + 1))
        if page_no in seen_page_numbers:
            continue
        is_illust = entry.get("type") == "illustration"
        fingerprint = str(entry.get("page_fingerprint", "") or "")
        source_key = str(entry.get("source_key", "") or "")
        if not is_illust:
            if fingerprint and fingerprint in seen_fingerprints:
                continue
            if source_key and source_key in seen_source_keys:
                continue
        text_hash = ""
        if entry.get("type") == "text":
            paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
            normalized = "".join(re.sub(r"\s+", "", paragraph.plain_text) for paragraph in paragraphs)
            if len(normalized) >= 140:
                text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                if text_hash in seen_text_hashes:
                    continue
        seen_page_numbers.add(page_no)
        if not is_illust:
            if fingerprint:
                seen_fingerprints.add(fingerprint)
            if source_key:
                seen_source_keys.add(source_key)
        if text_hash:
            seen_text_hashes.add(text_hash)
        result.append(entry)
    return result


def _scene_text(text: str, scene_break_style: str) -> str:
    if scene_break_style == "stars":
        return "＊　＊　＊"
    if scene_break_style == "original":
        return text
    return "__hr__"


def _collect_printed_toc_titles(entries: List[Dict]) -> List[Tuple[str, str, str]]:
    toc_titles: List[Tuple[str, str, str]] = []
    seen = set()
    for entry in entries:
        if entry.get("type") != "text":
            continue
        paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
        if not is_printed_toc_page(paragraphs):
            continue
        for paragraph in paragraphs:
            text = _clean_ruby(paragraph.plain_text).strip()
            if not text or TOC_TITLE_RE.match(text) or paragraph.block_type == "toc_title" or paragraph.is_scene_break:
                continue
            clean_title = _toc_text(_copy_spans(paragraph))
            if not clean_title:
                continue
            full_key = _plain_key(clean_title)
            stripped = PREFIX_STRIP_RE.sub("", clean_title).strip()
            suffix_key = _plain_key(stripped) if len(_plain_key(stripped)) >= 2 else ""
            if full_key and full_key not in seen:
                seen.add(full_key)
                toc_titles.append((clean_title, full_key, suffix_key))
    return toc_titles


def _match_printed_toc(text: str, para: OCRParagraph, para_idx: int, toc_titles: List[Tuple[str, str, str]]) -> Optional[str]:
    if not toc_titles or para.is_scene_break or para.is_toc_entry:
        return None
    if len(text) > 70 or text.startswith(("「", "『", "【", "（", "(")) or text.endswith(("。", "、", "」", "』")):
        return None
    para_key = _plain_key(text)
    if len(para_key) < 2:
        return None
    stripped_para = PREFIX_STRIP_RE.sub("", text).strip()
    para_suffix = _plain_key(stripped_para)
    looks_like_title = (
        para_idx <= 4
        or para.is_heading
        or para.is_all_bold
        or bool(SYMBOL_CHAPTER_RE.match(text))
        or para.block_type in {"chapter_heading", "section_heading", "subheading"}
    )
    for full_title, full_key, suffix_key in toc_titles:
        if para_key == full_key:
            return full_title
        if looks_like_title and suffix_key and len(suffix_key) >= 3 and (para_key == suffix_key or para_suffix == suffix_key):
            return full_title
    return None


def _merge_roman_headings(paragraphs: List[OCRParagraph]) -> List[OCRParagraph]:
    if len(paragraphs) < 2:
        return paragraphs
    merged: List[OCRParagraph] = []
    idx = 0
    while idx < len(paragraphs):
        cur = paragraphs[idx]
        cur_text = _clean_ruby(cur.plain_text).strip()
        if idx + 1 < len(paragraphs) and ROMAN_ALONE_RE.match(cur_text):
            nxt = paragraphs[idx + 1]
            nxt_text = _clean_ruby(nxt.plain_text).strip()
            if nxt_text and len(nxt_text) <= 60 and not nxt.is_scene_break and (nxt.is_heading or nxt.is_all_bold or SYMBOL_CHAPTER_RE.match(nxt_text)):
                spans = _copy_spans(cur)
                if spans:
                    spans[-1].text = spans[-1].text.rstrip() + " "
                spans.extend(_copy_spans(nxt))
                combined = OCRParagraph(
                    spans=spans,
                    ends_open=nxt.ends_open,
                    is_scene_break=False,
                    is_heading=True,
                    heading_level=1,
                    block_type="chapter_heading",
                    reading_order=cur.reading_order,
                    is_toc_entry=False,
                    is_toc_candidate=True,
                )
                merged.append(combined)
                idx += 2
                continue
        merged.append(cur)
        idx += 1
    return merged


def organize_entries_to_chapters(entries: List[Dict], scene_break_style: str = "stars") -> List[EpubChapter]:
    deduped = deduplicate_entries(entries)
    printed_toc_titles = _collect_printed_toc_titles(deduped)
    chapters = []
    current = EpubChapter("")
    current_is_toc = False
    last_chapter_page = -10
    recent_chapter_pages: Dict[str, int] = {}

    def flush():
        nonlocal current, current_is_toc
        if current.items:
            chapters.append(current)
        current = EpubChapter("")
        current_is_toc = False

    for entry in deduped:
        page_no = int(entry.get("page_no", 0))
        if entry.get("type") == "illustration":
            current.items.append({
                "type": "illustration",
                "image": entry.get("image"),
                "image_path": entry.get("image_path"),
                "image_size": entry.get("image_size"),
                "page_no": page_no,
                "source_name": entry.get("source_name", ""),
                "reason": entry.get("reason", ""),
                "page_fingerprint": entry.get("page_fingerprint", ""),
                "is_cover": bool(entry.get("is_cover", page_no == 1 and not chapters and not current.items)),
            })
            continue
        paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
        if not paragraphs:
            continue
        is_toc = is_printed_toc_page(paragraphs)
        if is_toc and not current_is_toc:
            flush()
            toc_title = "Table of Contents"
            current = EpubChapter(toc_title)
            current_is_toc = True
            current.items.append({"type": "heading", "text": toc_title, "level": 1, "page_no": page_no})
        elif current_is_toc and not is_toc:
            flush()
        if is_toc:
            for paragraph in paragraphs:
                text = _clean_ruby(paragraph.plain_text).strip()
                if not text or TOC_TITLE_RE.match(text) or paragraph.block_type == "toc_title":
                    continue
                if paragraph.is_scene_break:
                    current.items.append({"type": "scene_break", "text": _scene_text(text, scene_break_style), "page_no": page_no})
                else:
                    current.items.append({"type": "toc_entry", "spans": _copy_spans(paragraph), "page_no": page_no})
            continue
        paragraphs = _merge_roman_headings(paragraphs)
        for para_idx, paragraph in enumerate(paragraphs):
            text = _clean_ruby(paragraph.plain_text).strip()
            if not text:
                continue
            if paragraph.is_scene_break:
                current.items.append({"type": "scene_break", "text": _scene_text(text, scene_break_style), "page_no": page_no})
            elif paragraph.is_toc_entry or paragraph.block_type == "toc_entry":
                current.items.append({"type": "toc_entry", "spans": _copy_spans(paragraph), "page_no": page_no})
            else:
                toc_matched_title = _match_printed_toc(text, paragraph, para_idx, printed_toc_titles)
                if toc_matched_title or is_chapter_heading(paragraph):
                    title = toc_matched_title or text
                    t_key = _plain_key(title)
                    cur_key = _plain_key(current.title)
                    cur_para_count = sum(1 for it in current.items if it.get("type") == "paragraph")
                    if t_key and cur_key == t_key and (page_no - last_chapter_page <= 3 or cur_para_count <= 5):
                        current.items.append({"type": "paragraph", "spans": _copy_spans(paragraph), "page_no": page_no})
                        continue
                    if t_key and t_key in recent_chapter_pages and page_no - recent_chapter_pages[t_key] <= 3:
                        current.items.append({"type": "paragraph", "spans": _copy_spans(paragraph), "page_no": page_no})
                        continue
                    if current.title and cur_para_count == 0 and len(current.items) == 1 and page_no == last_chapter_page:
                        prev_heading = current.items[0].get("text", "")
                        current = EpubChapter(
                            title,
                            [
                                {"type": "heading", "text": title, "level": 1, "page_no": page_no},
                                {"type": "subheading", "text": prev_heading, "level": 2, "page_no": page_no},
                            ],
                        )
                        last_chapter_page = page_no
                        if t_key:
                            recent_chapter_pages[t_key] = page_no
                        continue
                    flush()
                    current = EpubChapter(title, [{"type": "heading", "text": title, "level": 1, "page_no": page_no}])
                    last_chapter_page = page_no
                    if t_key:
                        recent_chapter_pages[t_key] = page_no
                elif is_section_heading(paragraph):
                    current.items.append({"type": "subheading", "text": text, "level": max(2, min(3, paragraph.heading_level or 2)), "page_no": page_no})
                else:
                    current.items.append({"type": "paragraph", "spans": _copy_spans(paragraph), "page_no": page_no})
    flush()
    return chapters