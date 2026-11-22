import re
from typing import List

from core.gemini.markup import (
    extract_tagged_segments,
    parse_inline_bold_spans,
    strip_ruby_tags,
    strip_structure_tags,
)
from core.ocr import OCRParagraph, TextSpan, clean_japanese_ocr_artifacts, is_scene_break_text

_HANGUL_CHAR_RE = re.compile(r"[\uAC00-\uD7A3]")


def parse_page_paragraphs(raw_paras: List[dict], ends_open: bool, p_no: int, language: str) -> List[OCRParagraph]:
    ordered_raw = []
    for idx, para in enumerate(raw_paras):
        if not isinstance(para, dict):
            continue
        try:
            reading_order = int(para.get("reading_order", idx))
        except (TypeError, ValueError):
            reading_order = idx
        txt = clean_japanese_ocr_artifacts(strip_ruby_tags(str(para.get("text", "")).strip()), language)
        if txt:
            ordered_raw.append((reading_order, idx, para, txt))
    if ordered_raw and any(order >= 0 for order, _, _, _ in ordered_raw):
        ordered_raw.sort(key=lambda item: (item[0] if item[0] >= 0 else item[1], item[1]))

    if language == "ja" and ordered_raw:
        joined_check = "".join(strip_structure_tags(item[3]) for item in ordered_raw)

    para_objs: List[OCRParagraph] = []
    next_order = 0
    for idx, (_, _, para, txt) in enumerate(ordered_raw):
        block_type = str(para.get("block_type", "paragraph") or "paragraph").lower()
        try:
            heading_level = max(0, min(3, int(para.get("heading_level", 0) or 0)))
        except (TypeError, ValueError):
            heading_level = 0
        is_heading = bool(para.get("is_heading", False)) or block_type in ("chapter_heading", "section_heading", "divider")
        is_toc_entry = bool(para.get("is_toc_entry", False)) or block_type == "toc_entry"
        clean_plain_txt = strip_structure_tags(txt)
        is_sb = bool(para.get("is_scene_break", False)) or block_type == "scene_break" or is_scene_break_text(clean_plain_txt)
        whole_bold = bool(para.get("is_bold", False))
        is_last = idx == len(ordered_raw) - 1
        low_txt = txt.lower()

        if is_sb:
            spans = [TextSpan(re.sub(r"</?b>", "", clean_plain_txt, flags=re.IGNORECASE), False)]
            para_objs.append(
                OCRParagraph(
                    spans=spans,
                    ends_open=False,
                    is_scene_break=True,
                    is_heading=is_heading,
                    heading_level=heading_level,
                    block_type=block_type,
                    reading_order=next_order,
                    is_toc_entry=is_toc_entry,
                )
            )
            next_order += 1
        elif is_toc_entry or block_type == "toc_title":
            has_title = "<title" in low_txt or "<ft" in low_txt
            has_bic = "<bic" in low_txt
            spans = parse_inline_bold_spans(clean_plain_txt, whole_bold=whole_bold)
            para_objs.append(
                OCRParagraph(
                    spans=spans,
                    ends_open=(ends_open and is_last),
                    is_scene_break=False,
                    is_heading=is_heading,
                    heading_level=heading_level,
                    block_type=block_type,
                    reading_order=next_order,
                    is_toc_entry=is_toc_entry,
                    is_toc_candidate=has_title,
                    is_bic_candidate=has_bic,
                )
            )
            next_order += 1
        else:
            segments = extract_tagged_segments(txt)
            if not segments:
                fallback_tag = "bic" if "<bic" in low_txt else ("title" if ("<title" in low_txt or "<ft" in low_txt) else "")
                segments = [(clean_plain_txt, fallback_tag)]
            for sub_idx, (sub_txt, seg_tag) in enumerate(segments):
                is_sub_last = sub_idx == len(segments) - 1
                sub_clean = strip_structure_tags(sub_txt)
                if not sub_clean.strip():
                    continue
                spans = parse_inline_bold_spans(sub_clean, whole_bold=whole_bold)
                seg_has_tag = bool(seg_tag)
                seg_heading = is_heading and (seg_has_tag or len(segments) == 1)
                seg_level = heading_level if seg_heading else 0
                seg_type = block_type if seg_heading else "paragraph"
                para_objs.append(
                    OCRParagraph(
                        spans=spans,
                        ends_open=(ends_open and is_last and is_sub_last and not seg_has_tag),
                        is_scene_break=is_scene_break_text(sub_clean),
                        is_heading=seg_heading,
                        heading_level=seg_level,
                        block_type=seg_type,
                        reading_order=next_order,
                        is_toc_entry=False,
                        is_toc_candidate=(seg_tag == "title") or (seg_heading and seg_tag != "bic"),
                        is_bic_candidate=(seg_tag == "bic"),
                    )
                )
                next_order += 1
    return para_objs
