from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ProcessOptions:
    input_dir: Path
    output_path: Path
    mode: str
    text_extractor: str = "gemini"
    parallel_workers: int = 4
    split_enabled: bool = True
    split_skip_first: bool = True
    split_only_wide: bool = True
    split_large_images: bool = False
    read_direction: str = "RTL"
    trim_enabled: bool = True
    trim_top: bool = True
    trim_bottom: bool = True
    trim_left: bool = True
    trim_right: bool = True
    white_threshold: int = 240
    trim_padding: int = 1
    small_illust_enabled: bool = True
    trim_before_illust_detect: bool = True
    remove_text_header: bool = True
    header_cut_mode: str = "auto"
    crop_illustrations: bool = False
    header_top_pct: float = 6.0
    footer_bottom_pct: float = 0.0
    gemini_api_keys: str = ""
    gemini_model: str = "gemini-3.1-flash-lite"
    gemini_rpm: int = 10
    gemini_batch_size: int = 4
    gemini_max_concurrent: int = 4
    gemini_temperature: float = 0.0
    gemini_temp_step: float = 0.0
    gemini_max_retries: int = 3
    gemini_z_threshold: float = 2.5
    gemini_z_retry: bool = False
    gemini_on_fail_action: str = "ask"
    gemini_final_review: bool = True
    gemini_review_ocr: bool = True
    gemini_review_paragraphs: bool = True
    gemini_review_headings: bool = True
    gemini_review_toc: bool = True
    gemini_review_illust_toc: bool = True
    gemini_review_duplicates: bool = True
    gemini_review_illustrations: bool = True
    gemini_review_passes: int = 2
    gemini_review_batch_size: int = 15
    gemini_illust_toc_batch_size: int = 5
    gemini_missing_toc_batch_size: int = 8
    extra_prompts: Optional[Dict[str, str]] = None
    ocr_language: str = "ja"
    ocr_orientation: str = "vertical"
    illust_sensitivity: str = "normal"
    scene_break_style: str = "stars"
    resume_from_backup: bool = True
    book_title: str = ""
    make_epub: bool = True
    epub_writing_mode: str = "horizontal"
    epub_design: Optional[Dict] = None
    save_txt_folder: bool = True
    cover_crop_enabled: bool = False
    cover_crop_rect: Optional[tuple] = None
    classification_overrides: Optional[Dict[str, bool]] = None
    illust_trim_overrides: Optional[Dict[str, bool]] = None
    illust_side_crops: Optional[Dict[str, list]] = None
    illust_no_merge: Optional[Dict[str, bool]] = None


@dataclass
class EpubOnlyOptions:
    source_path: Path
    epub_path: Path
    book_title: str
    writing_mode: str = "horizontal"
    scene_break_style: str = "stars"
    epub_design: Optional[Dict] = None


@dataclass
class ExtractGlossaryOptions:
    epub_path: Path
    api_keys: str
    model_name: str = "gemini-3.1-flash-lite"
    rpm_per_key: int = 10
    max_concurrent: int = 4
    chunk_chars: int = 15000
    target_lang: str = "ko"
    sample_pct: int = 20
    append: bool = True
    existing_entries: Optional[Dict[str, str]] = None