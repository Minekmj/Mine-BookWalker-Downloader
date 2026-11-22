import hashlib
from pathlib import Path
from typing import List, Optional

from core.gemini import parse_inline_bold_spans
from core.gemini.markup import extract_tagged_segments, strip_structure_tags
from core.vision.image_utils import image_fingerprint, save_tmp_image
from core.vision.novel_detector import SplitPart
from core.ocr import OCRParagraph, is_scene_break_text


class EntryMixin():
    def _source_key(
        self,
        source_name: str,
        part_index: int,
        part: SplitPart,
        trim_override: Optional[bool] = None,
        fingerprint: Optional[str] = None,
    ) -> str:
        default_trim = False if getattr(part, "is_mini_illust", False) else self.opts.trim_enabled
        effective_trim = default_trim if trim_override is None else bool(trim_override)
        fp = fingerprint or part.fingerprint or image_fingerprint(part.image)
        payload = (
            9,
            source_name,
            part_index,
            fp,
            bool(part.is_illustration),
            bool(part.header_cut_applied),
            bool(getattr(part, "is_mini_illust", False)),
            self.opts.remove_text_header,
            self.opts.header_cut_mode,
            self.opts.header_top_pct,
            effective_trim,
            self.opts.trim_top,
            self.opts.trim_bottom,
            self.opts.trim_left,
            self.opts.trim_right,
            self.opts.trim_padding,
            self.opts.white_threshold,
            self.opts.small_illust_enabled,
            self.opts.trim_before_illust_detect,
            self.opts.crop_illustrations,
            self.opts.illust_sensitivity,
            self.opts.gemini_model,
            self.opts.ocr_language,
            self.opts.ocr_orientation,
        )
        return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _paragraphs_to_editable_text(paragraphs: List[OCRParagraph]) -> str:
        lines = []
        for paragraph in paragraphs:
            line = "".join(f"<b>{span.text}</b>" if span.is_bold else span.text for span in paragraph.spans)
            if not paragraph.is_scene_break and line.strip():
                if paragraph.is_toc_candidate:
                    line = f"<title>{line}</title>"
                elif paragraph.is_bic_candidate:
                    line = f"<bic>{line}</bic>"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _editable_text_to_paragraphs(raw_text: str) -> List[OCRParagraph]:
        paragraphs = []
        for index, (text, seg_tag) in enumerate(extract_tagged_segments(raw_text)):
            clean_text = strip_structure_tags(text)
            if not clean_text.strip():
                continue
            is_scene = is_scene_break_text(clean_text)
            paragraphs.append(
                OCRParagraph(
                    spans=parse_inline_bold_spans(clean_text, False),
                    is_scene_break=is_scene,
                    reading_order=index,
                    is_toc_candidate=(seg_tag == "title") and not is_scene,
                    is_bic_candidate=(seg_tag == "bic") and not is_scene,
                )
            )
        return paragraphs

    def _make_text_entry(
        self,
        page_no,
        source_name,
        part_index,
        part,
        source_key,
        paragraphs,
        ocr_error="",
        fingerprint: Optional[str] = None,
    ):
        fp = fingerprint or part.fingerprint or image_fingerprint(part.image)
        return {
            "type": "text",
            "page_no": page_no,
            "source_name": source_name,
            "source_part_index": part_index,
            "source_key": source_key,
            "page_fingerprint": fp,
            "paragraphs": paragraphs,
            "ocr_error": ocr_error,
        }

    def _make_illustration_entry(
        self,
        page_no,
        source_name,
        part_index,
        part,
        source_key,
        reason="",
        trim_override: Optional[bool] = None,
        raw_image=None,
        fingerprint: Optional[str] = None,
        save_dir: Optional[Path] = None,
    ):
        src_img = raw_image if raw_image is not None else part.image
        fp = fingerprint or part.fingerprint or image_fingerprint(src_img)
        prepared = self._prepare_illustration(
            src_img,
            header_cut_applied=bool(part.header_cut_applied),
            trim_override=trim_override,
            is_mini_illust=bool(getattr(part, "is_mini_illust", False)),
        )
        img_size = list(prepared.size)
        if save_dir is not None:
            out_path = save_dir / f"illust_{page_no:04d}.png"
            save_tmp_image(prepared, out_path)
            return {
                "type": "illustration",
                "page_no": page_no,
                "source_name": source_name,
                "source_part_index": part_index,
                "source_key": source_key,
                "page_fingerprint": fp,
                "image": None,
                "image_path": str(out_path),
                "image_size": img_size,
                "reason": reason or part.analysis_reason,
                "is_cover": page_no == 1,
            }
        return {
            "type": "illustration",
            "page_no": page_no,
            "source_name": source_name,
            "source_part_index": part_index,
            "source_key": source_key,
            "page_fingerprint": fp,
            "image": prepared.copy(),
            "image_size": img_size,
            "reason": reason or part.analysis_reason,
            "is_cover": page_no == 1,
        }