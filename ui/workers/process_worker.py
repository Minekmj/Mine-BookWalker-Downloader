from concurrent.futures import ThreadPoolExecutor, as_completed
import gc
import os
from pathlib import Path
import shutil
import threading
import time
import traceback
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from core.exporters import export_manga_pdf, export_manga_zip
from core.image_utils import (
    crop_normalized_rect,
    image_fingerprint,
    is_blank_image,
    list_images_in_folder,
    load_image_rgb,
    save_tmp_image,
)
from core.novel_detector import SplitPart
from core.page_pipeline import compute_base_parts, render_illustration_image
from core.paths import DIR_TMP
from ui.workers.entries import EntryMixin
from ui.workers.novel import NovelMixin
from ui.workers.options import ProcessOptions
from ui.workers.review import ReviewMixin


class ProcessWorker(EntryMixin, NovelMixin, ReviewMixin, QThread):
    progress = Signal(int, int)
    progress_stage = Signal(str)
    token_usage = Signal(int, int, int)
    log = Signal(str)
    review_needed = Signal(object)
    correction_preview_needed = Signal(object)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, opts: ProcessOptions):
        super().__init__()
        self.opts = opts
        self._cancelled = False
        self._review_event = threading.Event()
        self._review_decision = {}
        self._run_tmp_dir: Optional[Path] = None

    def cancel(self):
        self._cancelled = True
        self._review_decision = {"action": "cancel"}
        self._review_event.set()

    def set_review_decision(self, decision: Dict):
        self._review_decision = decision or {"action": "keep_edited"}
        self._review_event.set()

    def _ask_user_review(self, payload: Dict) -> Dict:
        self._review_event.clear()
        self.review_needed.emit(payload)
        self._review_event.wait()
        return self._review_decision

    def _ask_user_correction_preview(self, payload: Dict) -> Dict:
        self._review_event.clear()
        self.correction_preview_needed.emit(payload)
        self._review_event.wait()
        return self._review_decision

    def _pipeline_params(self) -> Dict:
        return {
            "split_enabled": self.opts.split_enabled,
            "split_skip_first": self.opts.split_skip_first,
            "split_only_wide": self.opts.split_only_wide,
            "split_large_images": self.opts.split_large_images,
            "read_direction": self.opts.read_direction,
            "illust_sensitivity": self.opts.illust_sensitivity,
            "remove_text_header": self.opts.remove_text_header,
            "crop_illustrations": self.opts.crop_illustrations,
            "header_top_pct": self.opts.header_top_pct,
            "footer_bottom_pct": self.opts.footer_bottom_pct,
            "header_cut_mode": self.opts.header_cut_mode,
            "small_illust_enabled": self.opts.small_illust_enabled,
            "trim_before_illust_detect": self.opts.trim_before_illust_detect,
            "trim_enabled": self.opts.trim_enabled,
            "trim_top": self.opts.trim_top,
            "trim_bottom": self.opts.trim_bottom,
            "trim_left": self.opts.trim_left,
            "trim_right": self.opts.trim_right,
            "white_threshold": self.opts.white_threshold,
            "trim_padding": self.opts.trim_padding,
        }

    def run(self):
        run_tmp = DIR_TMP / f"run_{os.getpid()}_{int(time.time() * 1000)}"
        run_tmp.mkdir(parents=True, exist_ok=True)
        self._run_tmp_dir = run_tmp
        try:
            files = list_images_in_folder(self.opts.input_dir)
            if not files:
                raise RuntimeError("선택한 폴더에 이미지 파일이 없습니다.")
            workers = max(1, min(64, int(self.opts.parallel_workers)))
            self.log.emit(f"총 {len(files)}개 이미지")
            self.progress_stage.emit(f"1/5 이미지 분할·분석 (0/{len(files)})")
            self.progress.emit(0, len(files))
            results_by_index = [[] for _ in files]
            completed = 0
            pipeline_params = self._pipeline_params()

            def split_one(index: int, path: Path):
                source = load_image_rgb(path)
                if self.opts.mode == "manga" and index == 0 and self.opts.cover_crop_enabled and self.opts.cover_crop_rect:
                    cropped = crop_normalized_rect(source, self.opts.cover_crop_rect)
                    parts = [SplitPart(cropped, "첫 장 표지 영역 자르기", True, "사용자 지정 표지 영역")]
                else:
                    parts = compute_base_parts(source, index == 0, self.opts.mode != "manga", pipeline_params)
                overrides = self.opts.classification_overrides or {}
                resolved_items = []
                for part_index, part in enumerate(parts):
                    fp = image_fingerprint(part.image)
                    blank = is_blank_image(part.image)
                    key = f"{path.name}::{part_index}::{fp}"
                    is_illustration = part.is_illustration
                    analysis_reason = part.analysis_reason
                    if key in overrides:
                        is_illustration = bool(overrides[key])
                        analysis_reason = "사용자 지정 삽화" if is_illustration else "사용자 지정 본문"
                    resolved_items.append((part_index, part, fp, blank, is_illustration, analysis_reason))

                no_merge = self.opts.illust_no_merge or {}
                if self.opts.mode == "novel" and not self.opts.split_large_images and not no_merge.get(path.name, False) and len(resolved_items) > 1:
                    non_blank = [item for item in resolved_items if not item[3]]
                    if len(non_blank) >= 2 and all(item[4] for item in non_blank):
                        fp = image_fingerprint(source)
                        blank = is_blank_image(source)
                        key = f"{path.name}::0::{fp}"
                        is_illustration = True
                        analysis_reason = "분리된 양면 삽화 자동 병합"
                        if key in overrides:
                            is_illustration = bool(overrides[key])
                            analysis_reason = "사용자 지정 삽화" if is_illustration else "사용자 지정 본문"
                        merged_part = SplitPart(
                            source,
                            "양면 삽화 병합",
                            is_illustration,
                            analysis_reason,
                            header_cut_applied=False,
                        )
                        resolved_items = [(0, merged_part, fp, blank, is_illustration, analysis_reason)]

                part_entries = []
                for part_index, part, fp, blank, is_illustration, analysis_reason in resolved_items:
                    part_path = None
                    if not blank:
                        part_path = save_tmp_image(part.image, run_tmp / f"part_{index:05d}_{part_index:02d}.png")
                    meta = SplitPart(
                        None,
                        part.split_note,
                        is_illustration,
                        analysis_reason,
                        header_cut_applied=part.header_cut_applied,
                        detected_header_cut_y=part.detected_header_cut_y,
                        is_mini_illust=part.is_mini_illust,
                        image_path=part_path,
                        fingerprint=fp,
                        is_blank=blank,
                    )
                    part_entries.append((part_index, meta, part_path, fp, blank))
                return index, part_entries

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(split_one, index, path) for index, path in enumerate(files)]
                for future in as_completed(futures):
                    if self._cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        self.finished_ok.emit("사용자에 의해 중지되었습니다.")
                        return
                    index, part_entries = future.result()
                    results_by_index[index] = part_entries
                    completed += 1
                    self.progress_stage.emit(f"1/5 이미지 분할·분석 ({completed}/{len(files)})")
                    self.progress.emit(completed, len(files))

            expanded_parts = [
                (path.name, part_index, meta, part_path, fp, blank)
                for path, part_entries in zip(files, results_by_index)
                for part_index, meta, part_path, fp, blank in part_entries
            ]
            results_by_index.clear()
            gc.collect()
            if self.opts.mode == "novel":
                seen = set()
                unique = []
                duplicates = 0
                for item in expanded_parts:
                    _, _, meta, _, fp, _ = item
                    if meta.is_illustration:
                        unique.append(item)
                        continue
                    if fp in seen:
                        duplicates += 1
                        continue
                    seen.add(fp)
                    unique.append(item)
                expanded_parts = unique
                if duplicates:
                    self.log.emit(f"픽셀이 완전히 동일한 중복 본문 페이지 {duplicates}장 제외")
            self.log.emit(f"분할 판정 후 총 {len(expanded_parts)}장")
            if self.opts.mode == "manga":
                self._run_manga(expanded_parts, workers)
            else:
                self._run_novel(expanded_parts, workers)
        except InterruptedError:
            self.finished_ok.emit("사용자에 의해 중지되었습니다.")
        except Exception as exc:
            detail = traceback.format_exc()
            self.log.emit(detail)
            err_msg = str(exc).strip() or type(exc).__name__
            self.failed.emit(err_msg)
        finally:
            self._run_tmp_dir = None
            shutil.rmtree(run_tmp, ignore_errors=True)
            gc.collect()

    def _prepare_illustration(
        self,
        raw_image,
        header_cut_applied: bool = False,
        trim_override: Optional[bool] = None,
        is_mini_illust: bool = False,
    ):
        if self.opts.mode == "manga":
            return raw_image.convert("RGB")
        part = SplitPart(raw_image, "", True, "", header_cut_applied=header_cut_applied, is_mini_illust=is_mini_illust)
        return render_illustration_image(part, self._pipeline_params(), trim_override=trim_override)

    def _run_manga(self, expanded_parts: List[tuple], workers: int):
        page_paths = [
            part_path
            for (_, _, _, part_path, _, blank) in expanded_parts
            if not blank and part_path is not None
        ]
        if not page_paths:
            raise RuntimeError("저장할 만화 페이지가 없습니다.")
        total = len(page_paths)
        self.log.emit(f"만화 모드: 파일 내보내기 중 ({total}장)")
        self.progress_stage.emit(f"만화 파일 내보내기 (0/{total})")
        self.progress.emit(0, total)
        self.opts.output_path.parent.mkdir(parents=True, exist_ok=True)

        def on_export_progress(done: int, count: int):
            if self._cancelled:
                raise InterruptedError("취소됨")
            self.progress_stage.emit(f"만화 파일 내보내기 ({done}/{count})")
            self.progress.emit(done, count)

        if self.opts.output_path.suffix.lower() == ".pdf":
            export_manga_pdf(page_paths, self.opts.output_path, progress_cb=on_export_progress)
            output_format = "PDF"
        else:
            export_manga_zip(page_paths, self.opts.output_path, progress_cb=on_export_progress)
            output_format = "ZIP"
        self.progress_stage.emit("완료")
        self.progress.emit(1, 1)
        self.finished_ok.emit(f"만화 {output_format} 생성 완료 ({total}장): {self.opts.output_path}")