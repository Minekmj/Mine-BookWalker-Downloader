import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_SETTINGS: Dict[str, Any] = {
    "input_dir": "",
    "mode": "novel",
    "manga_format": "pdf",
    "book_title": "",
    "parallel_workers": 12,
    "trim_top": True,
    "trim_bottom": True,
    "trim_left": True,
    "trim_right": True,
    "white_threshold": 240,
    "resume_from_backup": True,
    "make_epub": True,
    "save_txt_folder": True,
    "epub_theme": "default",
    "epub_font_family": "serif",
    "epub_font_size_pct": 100,
    "epub_line_height": 1.85,
    "epub_text_indent_em": 1.0,
    "epub_no_indent_dialogue": True,
    "epub_para_margin_em": 0.3,
    "epub_body_margin_em": 1.2,
    "epub_heading_style": "centered",
    "epub_chapter_page_break": True,
    "epub_illust_page_break": True,
    "epub_cover_enabled": True,
    "scene_break_style": "original",
    "split_enabled": True,
    "split_skip_first": False,
    "split_only_wide": True,
    "split_large_images": False,
    "illust_sensitivity": "sensitive",
    "trim_enabled": True,
    "trim_padding": 0,
    "small_illust_enabled": True,
    "trim_before_illust_detect": True,
    "remove_text_header": True,
    "header_cut_mode": "auto",
    "header_top_pct": 3.0,
    "crop_illustrations": True,
    "cover_crop_enabled": True,
    "cover_crop_rect": [
        0.24927894519983518,
        0.0,
        0.5014421096003296,
        0.999213217938631,
    ],
    "classification_overrides": {},
    "illust_trim_overrides": {},
    "illust_no_merge": {},
    "gemini_api_keys": "",
    "gemini_model": "gemini-3.1-flash-lite",
    "gemini_rpm": 15,
    "gemini_batch_size": 20,
    "gemini_max_concurrent": 15,
    "gemini_temperature": 0.1,
    "gemini_temp_step": 0.4,
    "gemini_max_retries": 3,
    "gemini_z_threshold": 2.5,
    "gemini_z_retry": False,
    "gemini_on_fail_action": "ask",
    "gemini_final_review": True,
    "gemini_review_ocr": True,
    "gemini_review_paragraphs": True,
    "gemini_review_headings": True,
    "gemini_review_toc": True,
    "gemini_review_illust_toc": True,
    "epub_register_dividers_in_toc": False,
    "gemini_review_duplicates": True,
    "gemini_review_illustrations": True,
    "gemini_review_passes": 1,
    "gemini_review_batch_size": 15,
    "gemini_illust_toc_batch_size": 5,
    "gemini_missing_toc_batch_size": 8,
    "prompt_extra_ocr": "",
    "prompt_extra_content_review": "",
    "prompt_extra_toc_reconcile": "",
    "prompt_extra_illust_toc": "",
    "prompt_extra_missing_toc": "",
    "prompt_extra_structure_audit": "",
    "web_dpr_scale": 3,
    "web_idle_ms": 500,
    "web_min_wait_ms": 200,
}

def load_app_settings(path: Path) -> Dict[str, Any]:
    data = dict(DEFAULT_SETTINGS)
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except Exception:
            pass
    return data


def save_app_settings(path: Path, data: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)