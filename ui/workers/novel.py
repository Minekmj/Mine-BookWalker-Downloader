from pathlib import Path
import threading
from typing import Dict, List

from core.epub import deduplicate_entries
from core.epub.styles import EpubDesignConfig
from core.exporters import export_light_novel, load_ocr_backup, save_ocr_backup
from core.gemini import GeminiTranscriber, parse_api_keys
from core.image_utils import load_image_rgb
from core.novel_detector import SplitPart
from core.page_pipeline import prepare_text_ocr_image
from core.paths import DIR_BACK_OCR, DIR_EPUB, DIR_OUT


class NovelMixin():
    def _emit_token_usage(self, transcriber):
        if transcriber is None:
            return
        usage = transcriber.get_token_usage()
        self.token_usage.emit(usage["input_tokens"], usage["output_tokens"], usage["total_tokens"])

    def _run_novel(self, expanded_parts: List[tuple], workers: int):
        book_name = self.opts.book_title.strip() or self.opts.input_dir.name or "output_novel"
        backup_dir = DIR_BACK_OCR / book_name
        backup_json = backup_dir / "ocr_backup.json"
        total = len(expanded_parts)
        entries_map = {}
        source_keys = {}
        trim_overrides = self.opts.illust_trim_overrides or {}
        pipeline_params = self._pipeline_params()
        path_by_page: Dict[int, Path] = {}
        part_meta_by_page: Dict[int, tuple] = {}
        run_tmp = getattr(self, "_run_tmp_dir", None)

        for page_no, (source_name, part_index, part, part_path, fp, blank) in enumerate(expanded_parts, start=1):
            if part_path is not None:
                path_by_page[page_no] = part_path
            part_meta_by_page[page_no] = (source_name, part_index, part, fp)
            override_key = f"{source_name}::{part_index}::{fp}"
            source_keys[page_no] = self._source_key(
                source_name,
                part_index,
                part,
                trim_override=trim_overrides.get(override_key),
                fingerprint=fp,
            )

        if self.opts.resume_from_backup and backup_json.is_file():
            try:
                old_entries = load_ocr_backup(backup_json)
                old_by_page = {entry["page_no"]: entry for entry in old_entries}
                reused = 0
                for page_no, entry in old_by_page.items():
                    if page_no <= total and entry.get("ocr_version", 0) >= 4 and entry.get("source_key") == source_keys.get(page_no):
                        entries_map[page_no] = entry
                        reused += 1
                self.log.emit(f"백업 확인: {reused}/{total}페이지 재사용")
            except Exception as exc:
                self.log.emit(f"백업을 읽지 못해 새로 인식합니다: {exc}")

        text_targets = []
        text_meta = {}
        illust_items = []
        for page_no, (source_name, part_index, part, part_path, fp, blank) in enumerate(expanded_parts, start=1):
            if blank or part_path is None:
                continue
            source_key = source_keys[page_no]
            if page_no in entries_map:
                continue
            if part.is_illustration:
                illust_items.append((page_no, source_name, part_index, part, part_path, fp, source_key))
            else:
                def make_loader(p_path=part_path, meta_p=part):
                    raw = load_image_rgb(p_path)
                    temp_part = SplitPart(
                        raw,
                        meta_p.split_note,
                        meta_p.is_illustration,
                        meta_p.analysis_reason,
                        header_cut_applied=meta_p.header_cut_applied,
                        detected_header_cut_y=meta_p.detected_header_cut_y,
                        is_mini_illust=meta_p.is_mini_illust,
                    )
                    return prepare_text_ocr_image(temp_part, pipeline_params)

                text_targets.append((page_no, make_loader))
                text_meta[page_no] = (source_name, part_index, part, source_key, make_loader, fp)

        if illust_items:
            ill_total = len(illust_items)
            self.progress_stage.emit(f"2/5 삽화 정리 (0/{ill_total})")
            self.progress.emit(0, ill_total)
            for idx, (page_no, source_name, part_index, part, part_path, fp, source_key) in enumerate(illust_items, start=1):
                if self._cancelled:
                    return
                override_key = f"{source_name}::{part_index}::{fp}"
                raw_img = load_image_rgb(part_path)
                entries_map[page_no] = self._make_illustration_entry(
                    page_no,
                    source_name,
                    part_index,
                    part,
                    source_key,
                    f"로컬 이미지 분석: {part.analysis_reason}",
                    trim_override=trim_overrides.get(override_key),
                    raw_image=raw_img,
                    fingerprint=fp,
                    save_dir=run_tmp,
                )
                self.log.emit(f"[{page_no}/{total}] 로컬 삽화 판정: {part.analysis_reason}")
                self.progress_stage.emit(f"2/5 삽화 정리 ({idx}/{ill_total})")
                self.progress.emit(idx, ill_total)

        api_keys = parse_api_keys(self.opts.gemini_api_keys)
        if not api_keys:
            raise RuntimeError("Gemini API 키가 입력되지 않았습니다.")
        transcriber = GeminiTranscriber(api_keys=api_keys, model_name=self.opts.gemini_model, rpm_per_key=self.opts.gemini_rpm, temperature=self.opts.gemini_temperature, temp_step=self.opts.gemini_temp_step, max_retries=self.opts.gemini_max_retries, language=self.opts.ocr_language, orientation=self.opts.ocr_orientation)
        failed_pages = {}
        ocr_ink_ratios: Dict[int, float] = {}
        ocr_used_temps: Dict[int, float] = {}
        ocr_total = len(text_targets)
        if text_targets:
            self.log.emit(f"Gemini OCR 시작: 본문 {ocr_total}페이지 | 묶음 {max(1, int(self.opts.gemini_batch_size))}장 | 동시 요청 {max(1, int(self.opts.gemini_max_concurrent))}")
            self.progress_stage.emit(f"2/5 Gemini OCR (0/{ocr_total})")
            self.progress.emit(0, ocr_total)
            lock = threading.Lock()
            ocr_done = 0

            def save_batch(batch_results):
                nonlocal ocr_done
                with lock:
                    for page_no, result in batch_results.items():
                        source_name, part_index, part, source_key, _, fp = text_meta[page_no]
                        if result.ink_ratio >= 0:
                            ocr_ink_ratios[page_no] = result.ink_ratio
                        ocr_used_temps[page_no] = result.used_temp
                        entries_map[page_no] = self._make_text_entry(
                            page_no,
                            source_name,
                            part_index,
                            part,
                            source_key,
                            result.paragraphs,
                            fingerprint=fp,
                        )
                        ocr_done += 1
                        char_count = sum(len(paragraph.plain_text) for paragraph in result.paragraphs)
                        self.log.emit(f"[{page_no}/{total}] OCR {char_count}자")
                        self.progress_stage.emit(f"2/5 Gemini OCR ({ocr_done}/{ocr_total})")
                        self.progress.emit(min(ocr_total, ocr_done), ocr_total)
                    save_ocr_backup(backup_dir, [entries_map[index] for index in sorted(entries_map)])
                    self._emit_token_usage(transcriber)

            _, failed_pages = transcriber.transcribe_pages_parallel(text_targets, batch_size=max(1, int(self.opts.gemini_batch_size)), max_concurrent=self.opts.gemini_max_concurrent, on_batch_done=save_batch, log_cb=self.log.emit, cancelled_fn=lambda: self._cancelled)
            if self._cancelled:
                save_ocr_backup(backup_dir, [entries_map[index] for index in sorted(entries_map)])
                self._emit_token_usage(transcriber)
                return
            for page_no, error in failed_pages.items():
                source_name, part_index, part, source_key, _, fp = text_meta[page_no]
                entries_map[page_no] = self._make_text_entry(
                    page_no,
                    source_name,
                    part_index,
                    part,
                    source_key,
                    [],
                    error,
                    fingerprint=fp,
                )
                ocr_done += 1
                self.log.emit(f"[OCR 실패] p{page_no}: 원본은 본문 분류로 유지 ({error})")
            self.progress_stage.emit(f"2/5 Gemini OCR ({ocr_total}/{ocr_total})")
            self.progress.emit(ocr_total, ocr_total)
            ocr_usage = transcriber.get_token_usage()
            self._emit_token_usage(transcriber)
            self.log.emit(f"OCR 토큰 사용량 · 입력 {ocr_usage['input_tokens']:,} / 출력 {ocr_usage['output_tokens']:,} (합계 {ocr_usage['total_tokens']:,})")
            self._review_ocr_anomalies(transcriber, text_targets, text_meta, entries_map, failed_pages, ocr_ink_ratios=ocr_ink_ratios, ocr_used_temps=ocr_used_temps)
        else:
            self.progress_stage.emit("2/5 OCR 백업 재사용")
            self.progress.emit(1, 1)

        text_targets.clear()
        text_meta.clear()

        if self._cancelled:
            save_ocr_backup(backup_dir, [entries_map[index] for index in sorted(entries_map)])
            self._emit_token_usage(transcriber)
            self.finished_ok.emit(f"중지됨 · 백업 저장 완료 ({backup_json})")
            return

        self.progress_stage.emit("4/5 EPUB·파일 생성 중")
        self.progress.emit(0, 2)
        entries = deduplicate_entries([entries_map[index] for index in sorted(entries_map)])
        save_ocr_backup(backup_dir, entries)
        self.progress.emit(1, 2)
        self.log.emit(f"백업 저장 완료: {backup_json}")
        design = EpubDesignConfig.from_dict(self.opts.epub_design or {})
        design.writing_mode = self.opts.epub_writing_mode
        design.scene_break_style = self.opts.scene_break_style
        epub_target = self.opts.output_path if self.opts.output_path.suffix.lower() == ".epub" else DIR_EPUB / f"{book_name}.epub"
        epub_out, chapters = export_light_novel(DIR_OUT, book_name, entries, epub_target, self.opts.save_txt_folder, self.opts.make_epub, design)
        self.progress.emit(2, 2)
        self.log.emit(f"생성된 장 {len(chapters)}개: " + " / ".join(chapter.title for chapter in chapters))

        def original_loader(p_no: int):
            p = path_by_page.get(p_no)
            return load_image_rgb(p) if p is not None and p.is_file() else None

        if transcriber is not None and epub_out is not None:
            self._run_final_gemini_check(
                transcriber,
                entries,
                chapters,
                epub_out,
                part_meta_by_page,
                original_loader,
                backup_dir,
            )

        total_usage = transcriber.get_token_usage()
        self._emit_token_usage(transcriber)
        usage_line = (
            f"총 토큰 사용량 · 입력 {total_usage['input_tokens']:,} / "
            f"출력 {total_usage['output_tokens']:,} "
            f"(합계 {total_usage['total_tokens']:,}, 요청 {total_usage['requests']:,}회)"
        )
        self.log.emit(usage_line)
        self.progress_stage.emit("완료")
        self.progress.emit(1, 1)
        message = (
            f"라노벨 변환 완료\nEPUB: {epub_out}\n{usage_line}"
            if epub_out
            else f"라노벨 TXT 변환 완료\n백업: {backup_json}\n{usage_line}"
        )
        self.finished_ok.emit(message)