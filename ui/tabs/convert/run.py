from pathlib import Path

from PySide6.QtWidgets import QMessageBox

from core.gemini import parse_api_keys
from core.config.paths import DIR_EPUB, DIR_OUT
from ui.dialogs.correction_preview_dialog import CorrectionPreviewDialog
from ui.dialogs.fail_dialog import FailureReviewDialog
from ui.workers import ProcessOptions, ProcessWorker


class RunMixin():
    def _set_button_running(self, running: bool):
        if running:
            self.btn_action.setText("중지")
            self.btn_action.setObjectName("dangerBtn")
        else:
            self.btn_action.setText("변환 시작")
            self.btn_action.setObjectName("primaryBtn")
        self.btn_action.style().unpolish(self.btn_action)
        self.btn_action.style().polish(self.btn_action)

    def _toggle_run_action(self):
        if self.worker and self.worker.isRunning():
            self._stop_process()
        else:
            self._start_process()

    def _start_process(self):
        in_text = self.input_edit.text().strip()
        if not in_text or not Path(in_text).is_dir():
            QMessageBox.warning(self, "경고", "원본 이미지 폴더를 선택하세요.")
            return

        is_novel = self._is_novel()
        title = self.book_title_edit.text().strip() or Path(in_text).name

        if is_novel:
            out_target = DIR_EPUB / f"{title}.epub"
        else:
            fmt = "pdf" if self._manga_format() == "pdf" else "zip"
            out_target = DIR_OUT / f"{title}.{fmt}"

        if is_novel:
            keys = parse_api_keys(str(self.adv.get("gemini_api_keys", "")))
            if not keys:
                QMessageBox.warning(self, "안내", "'Gemini API 키 · 속도 설정...' 버튼을 눌러 API 키를 입력하세요.")
                return

        self.settingsChanged.emit()

        opts = ProcessOptions(
            input_dir=Path(in_text),
            output_path=out_target,
            mode="novel" if is_novel else "manga",
            text_extractor="gemini",
            parallel_workers=int(self.adv.get("parallel_workers", 4)),
            split_enabled=self.chk_split.isChecked(),
            split_skip_first=self.chk_split_skip_first.isChecked(),
            split_only_wide=bool(self.adv.get("split_only_wide", True)),
            split_large_images=self.chk_split_large.isChecked(),
            read_direction="RTL",
            trim_enabled=is_novel and self.chk_trim.isChecked(),
            trim_top=bool(self.adv.get("trim_top", True)),
            trim_bottom=bool(self.adv.get("trim_bottom", True)),
            trim_left=bool(self.adv.get("trim_left", True)),
            trim_right=bool(self.adv.get("trim_right", True)),
            white_threshold=int(self.adv.get("white_threshold", 240)),
            trim_padding=int(self.adv.get("trim_padding", 1)),
            small_illust_enabled=is_novel and self.chk_small_illust.isChecked(),
            trim_before_illust_detect=is_novel and self.chk_trim_before_illust.isChecked(),
            remove_text_header=is_novel and self.chk_remove_header.isChecked(),
            crop_illustrations=is_novel and self.chk_crop_illust.isChecked(),
            header_top_pct=self.spin_header_top.value(),
            header_cut_mode=str(self.combo_header_cut.currentData()),
            footer_bottom_pct=0.0,
            gemini_api_keys=str(self.adv.get("gemini_api_keys", "")),
            gemini_model=str(self.adv.get("gemini_model", "gemini-3.1-flash-lite")),
            gemini_rpm=int(self.adv.get("gemini_rpm", 10)),
            gemini_batch_size=max(1, min(30, int(self.adv.get("gemini_batch_size", 4)))),
            gemini_max_concurrent=int(self.adv.get("gemini_max_concurrent", 4)),
            gemini_temperature=float(self.adv.get("gemini_temperature", 0.1)),
            gemini_temp_step=float(self.adv.get("gemini_temp_step", 0.4)),
            gemini_max_retries=int(self.adv.get("gemini_max_retries", 3)),
            gemini_z_threshold=float(self.adv.get("gemini_z_threshold", 2.5)),
            gemini_z_retry=bool(self.adv.get("gemini_z_retry", False)),
            gemini_on_fail_action=str(self.adv.get("gemini_on_fail_action", "ask")),
            gemini_final_review=bool(self.adv.get("gemini_final_review", True)),
            gemini_review_ocr=bool(self.adv.get("gemini_review_ocr", True)),
            gemini_review_paragraphs=bool(self.adv.get("gemini_review_paragraphs", True)),
            gemini_review_headings=bool(self.adv.get("gemini_review_headings", True)),
            gemini_review_toc=bool(self.adv.get("gemini_review_toc", True)),
            gemini_review_illust_toc=bool(self.adv.get("gemini_review_illust_toc", True)),
            gemini_review_duplicates=bool(self.adv.get("gemini_review_duplicates", True)),
            gemini_review_illustrations=bool(self.adv.get("gemini_review_illustrations", True)),
            gemini_review_passes=max(1, min(3, int(self.adv.get("gemini_review_passes", 2)))),
            gemini_review_batch_size=max(1, min(30, int(self.adv.get("gemini_review_batch_size", 15)))),
            gemini_illust_toc_batch_size=max(1, min(20, int(self.adv.get("gemini_illust_toc_batch_size", 5)))),
            gemini_missing_toc_batch_size=max(1, min(20, int(self.adv.get("gemini_missing_toc_batch_size", 8)))),
            extra_prompts={k: str(self.adv.get(k, "") or "").strip() for k in ("prompt_extra_ocr", "prompt_extra_content_review", "prompt_extra_toc_reconcile", "prompt_extra_illust_toc", "prompt_extra_missing_toc", "prompt_extra_structure_audit")},
            illust_sensitivity=str(self.adv.get("illust_sensitivity", "normal")),
            scene_break_style=str(self.adv.get("scene_break_style", "stars")),
            resume_from_backup=bool(self.adv.get("resume_from_backup", True)),
            book_title=title,
            make_epub=bool(self.adv.get("make_epub", True)),
            epub_writing_mode=str(self.adv.get("epub_writing_mode", "horizontal")),
            epub_design=dict(self.adv),
            save_txt_folder=bool(self.adv.get("save_txt_folder", True)),
            cover_crop_enabled=bool(self.chk_cover_crop.isChecked() and not is_novel and self._cover_crop_rect),
            cover_crop_rect=self._cover_crop_rect,
            classification_overrides=dict(self._classification_overrides),
            illust_trim_overrides=dict(self._illust_trim_overrides),
            illust_no_merge=dict(self._illust_no_merge),
        )

        self.log_box.clear()
        self.btn_log_toggle.setChecked(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setFormat("준비 중 · %p%")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.lbl_token_usage.setVisible(is_novel)
        self.lbl_token_usage.setText("토큰 사용량 · 입력 0 · 출력 0 · 합계 0")
        self._set_button_running(True)

        self.worker = ProcessWorker(opts)
        self.worker.progress.connect(self._on_progress)
        self.worker.progress_stage.connect(self._on_progress_stage)
        self.worker.token_usage.connect(self._on_token_usage)
        self.worker.log.connect(self.log_box.appendPlainText)
        self.worker.review_needed.connect(self._on_review_needed)
        self.worker.correction_preview_needed.connect(self._on_correction_preview_needed)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_review_needed(self, payload: dict):
        dlg = FailureReviewDialog(payload, self.adv, parent=self)
        dlg.exec()
        if self.worker:
            self.worker.set_review_decision(dlg.get_decision())

    def _on_correction_preview_needed(self, payload: dict):
        dlg = CorrectionPreviewDialog(payload, parent=self)
        dlg.exec()
        if self.worker:
            self.worker.set_review_decision(dlg.get_decision())

    def _stop_process(self):
        if self.worker:
            self.btn_action.setEnabled(False)
            self.progress_bar.setFormat("중지 요청 중...")
            self.worker.cancel()

    def _on_progress_stage(self, stage: str):
        self.progress_bar.setFormat(f"{stage} · %p%")

    def _on_token_usage(self, input_tokens: int, output_tokens: int, total_tokens: int):
        self.lbl_token_usage.setText(
            f"토큰 사용량 · 입력 {input_tokens:,} · 출력 {output_tokens:,} · 합계 {total_tokens:,}"
        )

    def _on_progress(self, current: int, total: int):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(min(max(0, current), total))

    def _cleanup_worker(self):
        w = getattr(self, "worker", None)
        if w is not None:
            try:
                w.wait(500)
                w.deleteLater()
            except RuntimeError:
                pass
            self.worker = None
        self.btn_action.setEnabled(True)

    def _on_finished(self, msg: str):
        self._cleanup_worker()
        self._set_button_running(False)
        self.progress_bar.setFormat("완료 · %p%")
        if self.progress_bar.maximum() > 0:
            self.progress_bar.setValue(self.progress_bar.maximum())
        self.log_box.appendPlainText(msg)
        QMessageBox.information(self, "완료", msg)

    def _on_failed(self, err: str):
        self._cleanup_worker()
        self._set_button_running(False)
        self.progress_bar.setFormat("오류 중단")
        self.log_box.appendPlainText(f"[오류] {err}")
        QMessageBox.critical(self, "오류", err)