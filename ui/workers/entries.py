import hashlib
from pathlib import Path
from typing import List, Optional

from core.gemini import parse_inline_bold_spans
from core.gemini.markup import extract_tagged_segments, strip_structure_tags
from core.vision.image_utils import image_fingerprint, save_tmp_image
from core.vision.novel_detector import SplitPart
from core.ocr import OCRParagraph, is_scene_break_text


_SOURCE_CONFIG_KEYS = (
    "split_enabled", "split_skip_first", "split_only_wide", "split_large_images", "read_direction",
    "remove_text_header", "header_cut_mode", "header_top_pct", "footer_bottom_pct", "crop_illustrations",
    "trim_enabled", "trim_top", "trim_bottom", "trim_left", "trim_right", "trim_padding", "trim_extra_px", "white_threshold",
    "small_illust_enabled", "trim_before_illust_detect", "illust_sensitivity", "gemini_model", "ocr_language", "ocr_orientation",
)
_SOURCE_MAP_KEYS = ("classification_overrides", "illust_trim_overrides", "illust_side_crops", "illust_no_merge", "no_auto_separate")


def _setting(settings, key, default=None):
    return settings.get(key, default) if isinstance(settings, dict) else getattr(settings, key, default)


def build_source_config(settings) -> dict:
    config = {key: _setting(settings, key) for key in _SOURCE_CONFIG_KEYS}
    config.update({key: dict(_setting(settings, key, {}) or {}) for key in _SOURCE_MAP_KEYS})
    return config


def build_source_key(settings, source_name, part_index, part, trim_override=None, fingerprint=None, side_crop=None) -> str:
    default_trim = False if getattr(part, "is_mini_illust", False) else bool(_setting(settings, "trim_enabled", True))
    effective_trim = default_trim if trim_override is None else bool(trim_override)
    fp = fingerprint or part.fingerprint or image_fingerprint(part.image)
    payload = (
        9, source_name, part_index, fp, bool(part.is_illustration), bool(part.header_cut_applied),
        bool(getattr(part, "is_mini_illust", False)), bool(_setting(settings, "remove_text_header", True)),
        str(_setting(settings, "header_cut_mode", "auto")), float(_setting(settings, "header_top_pct", 6.0)),
        effective_trim, bool(_setting(settings, "trim_top", True)), bool(_setting(settings, "trim_bottom", True)),
        bool(_setting(settings, "trim_left", True)), bool(_setting(settings, "trim_right", True)),
        int(_setting(settings, "trim_padding", 1)), int(_setting(settings, "white_threshold", 240)),
        bool(_setting(settings, "small_illust_enabled", True)), bool(_setting(settings, "trim_before_illust_detect", True)),
        bool(_setting(settings, "crop_illustrations", False)), str(_setting(settings, "illust_sensitivity", "normal")),
        str(_setting(settings, "gemini_model", "gemini-3.1-flash-lite")), str(_setting(settings, "ocr_language", "ja")),
        str(_setting(settings, "ocr_orientation", "vertical")),
        (round(float(side_crop[0]), 1), round(float(side_crop[1]), 1)) if side_crop and len(side_crop) == 2 else (0.0, 0.0),
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


class EntryMixin():
    def _source_key(self, source_name, part_index, part, trim_override=None, fingerprint=None, side_crop=None) -> str:
        return build_source_key(self.opts, source_name, part_index, part, trim_override, fingerprint, side_crop)

    def _source_config(self) -> dict:
        return build_source_config(self.opts)

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
            "source_config": self._source_config(),
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
        side_crop: Optional[tuple] = None,
    ):
        src_img = raw_image if raw_image is not None else part.image
        fp = fingerprint or part.fingerprint or image_fingerprint(src_img)
        prepared = self._prepare_illustration(
            src_img,
            header_cut_applied=bool(part.header_cut_applied),
            trim_override=trim_override,
            is_mini_illust=bool(getattr(part, "is_mini_illust", False)),
            side_crop=side_crop,
            side_crop_applied=bool(getattr(part, "side_crop_applied", False)),
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
                "source_config": self._source_config(),
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
            "source_config": self._source_config(),
        }