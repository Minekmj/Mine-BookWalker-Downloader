from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from core.gemini import parse_api_keys
from core.config.paths import DIR_BACK_OCR, DIR_EPUB, DIR_OUT
from ui.dialogs.correction_preview_dialog import CorrectionPreviewDialog
from ui.dialogs.fail_dialog import FailureReviewDialog
from ui.workers import EpubOnlyOptions, EpubOnlyWorker, ProcessOptions, ProcessWorker
from ui.workers.backup_check import BackupCheckWorker


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

    def _set_backup_status(self, text, tooltip="", state="neutral"):
        self.lbl_backup_status.setText(text)
        self.lbl_backup_status.setToolTip(tooltip or text)
        self.lbl_backup_status.setProperty("available", state == "ok")
        self.lbl_backup_status.setProperty("warning", state == "warning")
        self.lbl_backup_status.style().unpolish(self.lbl_backup_status)
        self.lbl_backup_status.style().polish(self.lbl_backup_status)

    def _update_backup_status(self, *_):
        self._schedule_backup_status_check()

    def _schedule_backup_status_check(self):
        if not hasattr(self, "_backup_check_generation"):
            self._backup_check_generation = 0
            self._backup_check_workers = []
            self._active_backup_check = None
            self._backup_check_timer = QTimer(self)
            self._backup_check_timer.setSingleShot(True)
            self._backup_check_timer.timeout.connect(self._start_backup_status_check)
        self._backup_check_generation += 1
        active = self._active_backup_check
        if active is not None and active.isRunning():
            active.cancel()
        self._backup_check_timer.start(400)

    def _backup_check_settings(self, input_dir):
        return {
            "input_dir": str(input_dir),
            "split_enabled": self.chk_split.isChecked(),
            "split_skip_first": self.chk_split_skip_first.isChecked(),
            "split_only_wide": bool(self.adv.get("split_only_wide", True)),
            "split_large_images": self.chk_split_large.isChecked(),
            "read_direction": "RTL",
            "illust_sensitivity": str(self.adv.get("illust_sensitivity", "normal")),
            "remove_text_header": self.chk_remove_header.isChecked(),
            "crop_illustrations": self.chk_crop_illust.isChecked(),
            "header_top_pct": self.spin_header_top.value(),
            "footer_bottom_pct": 0.0,
            "header_cut_mode": str(self.combo_header_cut.currentData()),
            "small_illust_enabled": self.chk_small_illust.isChecked(),
            "trim_before_illust_detect": self.chk_trim_before_illust.isChecked(),
            "trim_enabled": self.chk_trim.isChecked(),
            "trim_top": bool(self.adv.get("trim_top", True)),
            "trim_bottom": bool(self.adv.get("trim_bottom", True)),
            "trim_left": bool(self.adv.get("trim_left", True)),
            "trim_right": bool(self.adv.get("trim_right", True)),
            "white_threshold": int(self.adv.get("white_threshold", 240)),
            "trim_padding": int(self.adv.get("trim_padding", 1)),
            "gemini_model": str(self.adv.get("gemini_model", "gemini-3.1-flash-lite")),
            "ocr_language": "ja",
            "ocr_orientation": "vertical",
            "classification_overrides": dict(self._classification_overrides),
            "illust_trim_overrides": dict(self._illust_trim_overrides),
            "illust_side_crops": dict(self._illust_side_crops),
            "illust_no_merge": dict(self._illust_no_merge),
            "no_auto_separate": dict(self._no_auto_separate),
            "resume_from_backup": bool(self.adv.get("resume_from_backup", True)),
        }

    def _start_backup_status_check(self):
        if not self._is_novel():
            self._set_backup_status("백업 검사: 라노벨 모드에서 사용", "백업 이어하기 검사는 라노벨 EPUB 변환에서 사용합니다.")
            return
        input_text = self.input_edit.text().strip()
        input_dir = Path(input_text) if input_text else None
        title = self.book_title_edit.text().strip() or (input_dir.name if input_dir else "")
        if not title:
            self._set_backup_status("백업 없음", "책 제목 또는 원본 폴더를 지정하세요.")
            return
        backup_json = DIR_BACK_OCR / title / "ocr_backup.json"
        if not backup_json.is_file():
            self._set_backup_status("백업 없음", f"백업 파일이 없습니다.\n{backup_json}")
            return
        if input_dir is None or not input_dir.is_dir():
            self._set_backup_status("백업 있음 - 원본 폴더 선택 필요", f"백업은 있지만 현재 원본 이미지 폴더가 지정되지 않았습니다.\n{backup_json}", "warning")
            return
        if self.worker is not None and self.worker.isRunning():
            self._set_backup_status("백업 있음 - 변환 작업 종료 후 설정 검사", f"현재 변환 작업이 실행 중입니다.\n{backup_json}", "warning")
            return
        generation = self._backup_check_generation
        settings = self._backup_check_settings(input_dir)
        self._set_backup_status("백업 있음 - 현재 설정과 비교 중…", f"비동기로 원본 이미지 분할 결과와 실제 OCR 재사용 키를 비교합니다.\n{backup_json}")
        worker = BackupCheckWorker(settings, backup_json, self)
        self._active_backup_check = worker
        self._backup_check_workers.append(worker)
        worker.progress.connect(lambda done, total, g=generation, w=worker: self._on_backup_status_progress(g, w, done, total))
        worker.result.connect(lambda result, g=generation, w=worker: self._on_backup_status_result(g, w, result, settings))
        worker.finished.connect(lambda w=worker: self._on_backup_status_worker_finished(w))
        worker.start()

    def _on_backup_status_progress(self, generation, worker, done, total):
        if generation != self._backup_check_generation or worker is not self._active_backup_check:
            return
        self._set_backup_status(f"백업 있음 - 현재 설정 검사 중… ({done}/{total})", "원본 파일을 비동기로 분할·분석하고 변환 작업과 동일한 source_key를 계산하고 있습니다.")

    def _on_backup_status_result(self, generation, worker, result, settings):
        if generation != self._backup_check_generation or worker is not self._active_backup_check:
            return
        state = result.get("state")
        if state == "missing":
            self._set_backup_status("백업 없음", result.get("message", "백업 파일이 없습니다."))
            return
        if state in {"invalid", "legacy", "error"}:
            message = result.get("message", "백업을 재사용할 수 없습니다.")
            self._set_backup_status(f"백업 있음 - 재사용 불가: {message}", message, "warning")
            return
        matched = int(result.get("matched", 0))
        current = int(result.get("current", 0))
        mismatched = list(result.get("mismatched", []))
        missing = list(result.get("missing", []))
        orphaned = list(result.get("orphaned", []))
        reasons = result.get("reasons", {}) or {}
        changed_settings = list(result.get("changed_settings", []))
        changed_setting_values = list(result.get("changed_setting_values", []))
        old_config_missing = int(result.get("old_config_missing", 0))
        resume_enabled = bool(settings.get("resume_from_backup", True))
        if not resume_enabled:
            headline = f"백업 있음 - 이어하기 설정 필요 ({matched}/{current}페이지 재사용 가능)"
            state_style = "warning"
        elif current <= 0:
            headline = "백업 있음 - 현재 폴더에 OCR 대상 페이지 없음"
            state_style = "warning"
        elif matched == current:
            headline = f"백업 있음 - 현재 설정과 일치 ({matched}/{current}페이지 재사용 가능)"
            state_style = "ok"
        elif changed_settings:
            headline = f"백업 있음 - 설정 변경 필요 ({matched}/{current}페이지 재사용 가능)"
            state_style = "warning"
        elif missing and not mismatched:
            headline = f"백업 있음 - 신규 페이지 OCR 필요 ({matched}/{current}페이지 재사용 가능)"
            state_style = "warning"
        elif any("원본" in name or "분할 결과" in name or "분류 변경" in name for name in reasons):
            headline = f"백업 있음 - 원본 조건 확인 필요 ({matched}/{current}페이지 재사용 가능)"
            state_style = "warning"
        elif matched > 0 and (mismatched or missing):
            headline = f"백업 있음 - 일부 페이지 재인식 필요 ({matched}/{current}페이지 재사용 가능)"
            state_style = "warning"
        else:
            headline = f"백업 있음 - 재사용 조건 불일치 (0/{current}페이지 재사용 가능)"
            state_style = "warning"
        detail_lines = []
        if not resume_enabled:
            detail_lines.append("필요 조건: 고급 설정에서 '백업에서 이어하기'를 켜세요.")
        if changed_setting_values:
            restore_items = [f"{item['name']}: 현재 {item['current_value']} → 백업값 {item['backup_value']} ({item['pages']}페이지)" for item in changed_setting_values[:5]]
            detail_lines.append("재사용하려면 백업값으로 변경: " + " / ".join(restore_items))
        elif changed_settings:
            detail_lines.append("변경된 설정: " + ", ".join(changed_settings[:8]))
        if reasons:
            reason_names = set(reasons)
            detail_lines.append("불일치 이유: " + " / ".join(f"{name} {count}페이지" for name, count in sorted(reasons.items(), key=lambda pair: (-pair[1], pair[0]))[:4]))
            if any("원본 파일명" in name or "페이지 순서" in name for name in reason_names):
                detail_lines.append("필요 조건: OCR 백업 생성 당시의 원본 파일명과 파일 정렬 순서를 복원하세요.")
            if any("원본 이미지" in name for name in reason_names):
                detail_lines.append("필요 조건: 백업 생성에 사용한 원본 이미지 파일을 복원하세요. 이미지가 달라지면 설정만 바꿔서는 재사용할 수 없습니다.")
            if any("페이지 분할" in name for name in reason_names):
                detail_lines.append("필요 조건: 페이지 분할 설정을 백업 당시 값으로 되돌리세요.")
            if any("본문·삽화 분류" in name for name in reason_names):
                detail_lines.append("필요 조건: 미리보기에서 해당 페이지의 본문·삽화 분류를 백업 당시대로 복원하세요.")
        if old_config_missing and mismatched:
            detail_lines.append(f"구형 백업 설정 스냅샷 없음: {min(old_config_missing, len(mismatched))}페이지는 당시 설정값을 복원할 수 없어 OCR 설정의 정확한 변경 원인을 역추적할 수 없습니다.")
        if missing:
            detail_lines.append(f"백업에 없는 페이지: {len(missing)}개 ({', '.join(map(str, missing[:12]))})")
            detail_lines.append("필요 조건: 새로 추가된 페이지는 백업이 없으므로 OCR이 새로 실행됩니다. 기존 백업 설정을 바꿀 필요는 없습니다.")
        if mismatched:
            detail_lines.append(f"설정·원본 불일치 페이지: {len(mismatched)}개 ({', '.join(map(str, mismatched[:12]))})")
        if orphaned:
            detail_lines.append(f"현재 구성에 없는 오래된 백업 페이지: {len(orphaned)}개 ({', '.join(map(str, orphaned[:12]))})")
        detail_lines.append("이어하기 체크가 켜져 있으면 일치하는 페이지만 재사용하고 나머지만 다시 OCR합니다.")
        details = "\n".join(detail_lines)
        display = headline + ("\n" + " · ".join(detail_lines[:2]) if detail_lines else "")
        self._set_backup_status(display, headline + "\n" + details, state_style)

    def _on_backup_status_worker_finished(self, worker):
        if worker in self._backup_check_workers:
            self._backup_check_workers.remove(worker)
        if worker is self._active_backup_check:
            self._active_backup_check = None
        worker.deleteLater()

    def _toggle_run_action(self):
        if self.worker and self.worker.isRunning():
            self._stop_process()
        else:
            self._start_process()

    def _start_epub_only(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.warning(self, "작업 중", "현재 작업이 끝난 뒤 실행하세요.")
            return
        title = self.book_title_edit.text().strip() or Path(self.input_edit.text().strip()).name
        if not title:
            QMessageBox.warning(self, "안내", "책 제목 또는 원본 폴더를 지정하세요.")
            return
        backup_json = DIR_BACK_OCR / title / "ocr_backup.json"
        if not backup_json.is_file():
            QMessageBox.warning(self, "백업 없음", f"OCR 백업 파일을 찾을 수 없습니다.\n{backup_json}")
            return
        self.settingsChanged.emit()
        opts = EpubOnlyOptions(
            source_path=backup_json,
            epub_path=DIR_EPUB / f"{title}.epub",
            book_title=title,
            writing_mode=str(self.adv.get("epub_writing_mode", "horizontal")),
            scene_break_style=str(self.adv.get("scene_break_style", "stars")),
            epub_design=dict(self.adv),
        )
        self.log_box.clear()
        self.btn_log_toggle.setChecked(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("EPUB 재생성 준비 중 · %p%")
        self.btn_action.setEnabled(False)
        self.btn_epub_only.setEnabled(False)
        self.worker = EpubOnlyWorker(opts)
        self.worker.progress.connect(self._on_progress)
        self.worker.progress_stage.connect(self._on_progress_stage)
        self.worker.log.connect(self.log_box.appendPlainText)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

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
            input_dir=Path(in_text), output_path=out_target, mode="novel" if is_novel else "manga", text_extractor="gemini",
            parallel_workers=int(self.adv.get("parallel_workers", 4)), split_enabled=self.chk_split.isChecked(),
            split_skip_first=self.chk_split_skip_first.isChecked(), split_only_wide=bool(self.adv.get("split_only_wide", True)),
            split_large_images=self.chk_split_large.isChecked(), read_direction="RTL", trim_enabled=is_novel and self.chk_trim.isChecked(),
            trim_top=bool(self.adv.get("trim_top", True)), trim_bottom=bool(self.adv.get("trim_bottom", True)),
            trim_left=bool(self.adv.get("trim_left", True)), trim_right=bool(self.adv.get("trim_right", True)),
            white_threshold=int(self.adv.get("white_threshold", 240)), trim_padding=int(self.adv.get("trim_padding", 1)),
            small_illust_enabled=is_novel and self.chk_small_illust.isChecked(), trim_before_illust_detect=is_novel and self.chk_trim_before_illust.isChecked(),
            remove_text_header=is_novel and self.chk_remove_header.isChecked(), crop_illustrations=is_novel and self.chk_crop_illust.isChecked(),
            header_top_pct=self.spin_header_top.value(), header_cut_mode=str(self.combo_header_cut.currentData()), footer_bottom_pct=0.0,
            gemini_api_keys=str(self.adv.get("gemini_api_keys", "")), gemini_model=str(self.adv.get("gemini_model", "gemini-3.1-flash-lite")),
            gemini_rpm=int(self.adv.get("gemini_rpm", 10)), gemini_batch_size=max(1, min(30, int(self.adv.get("gemini_batch_size", 4)))),
            gemini_max_concurrent=int(self.adv.get("gemini_max_concurrent", 4)), gemini_temperature=float(self.adv.get("gemini_temperature", 0.1)),
            gemini_temp_step=float(self.adv.get("gemini_temp_step", 0.4)), gemini_max_retries=int(self.adv.get("gemini_max_retries", 3)),
            gemini_z_threshold=float(self.adv.get("gemini_z_threshold", 2.5)), gemini_z_retry=bool(self.adv.get("gemini_z_retry", False)),
            gemini_on_fail_action=str(self.adv.get("gemini_on_fail_action", "ask")), gemini_final_review=bool(self.adv.get("gemini_final_review", True)),
            gemini_review_ocr=bool(self.adv.get("gemini_review_ocr", True)), gemini_review_paragraphs=bool(self.adv.get("gemini_review_paragraphs", True)),
            gemini_review_headings=bool(self.adv.get("gemini_review_headings", True)), gemini_review_toc=bool(self.adv.get("gemini_review_toc", True)),
            gemini_review_illust_toc=bool(self.adv.get("gemini_review_illust_toc", True)), gemini_review_duplicates=bool(self.adv.get("gemini_review_duplicates", True)),
            gemini_review_illustrations=bool(self.adv.get("gemini_review_illustrations", True)), gemini_review_passes=max(1, min(3, int(self.adv.get("gemini_review_passes", 2)))),
            gemini_review_batch_size=max(1, min(30, int(self.adv.get("gemini_review_batch_size", 15)))),
            gemini_illust_toc_batch_size=max(1, min(20, int(self.adv.get("gemini_illust_toc_batch_size", 5)))),
            gemini_missing_toc_batch_size=max(1, min(20, int(self.adv.get("gemini_missing_toc_batch_size", 8)))),
            extra_prompts={k: str(self.adv.get(k, "") or "").strip() for k in ("prompt_extra_ocr", "prompt_extra_content_review", "prompt_extra_toc_reconcile", "prompt_extra_illust_toc", "prompt_extra_missing_toc", "prompt_extra_structure_audit")},
            illust_sensitivity=str(self.adv.get("illust_sensitivity", "normal")), scene_break_style=str(self.adv.get("scene_break_style", "stars")),
            resume_from_backup=bool(self.adv.get("resume_from_backup", True)), book_title=title, make_epub=bool(self.adv.get("make_epub", True)),
            epub_writing_mode=str(self.adv.get("epub_writing_mode", "horizontal")), epub_design=dict(self.adv), save_txt_folder=bool(self.adv.get("save_txt_folder", True)),
            cover_crop_enabled=bool(self.chk_cover_crop.isChecked() and not is_novel and self._cover_crop_rect), cover_crop_rect=self._cover_crop_rect,
            classification_overrides=dict(self._classification_overrides), illust_trim_overrides=dict(self._illust_trim_overrides),
            illust_side_crops=dict(self._illust_side_crops), illust_no_merge=dict(self._illust_no_merge), no_auto_separate=dict(self._no_auto_separate),
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
        self.lbl_token_usage.setText(f"토큰 사용량 · 입력 {input_tokens:,} · 출력 {output_tokens:,} · 합계 {total_tokens:,}")

    def _on_progress(self, current: int, total: int):
        if total > 0:
            self.progress_bar.setRange(0, total)
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
        if hasattr(self, "btn_epub_only"):
            self.btn_epub_only.setEnabled(True)

    def _on_finished(self, msg: str):
        self._cleanup_worker()
        self._set_button_running(False)
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.progress_bar.setFormat("완료 · %p%")
        self.log_box.appendPlainText(msg)
        self._schedule_backup_status_check()
        QMessageBox.information(self, "완료", msg)

    def _on_failed(self, err: str):
        self._cleanup_worker()
        self._set_button_running(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("오류 중단")
        self.log_box.appendPlainText(f"[오류] {err}")
        self._schedule_backup_status_check()
        QMessageBox.critical(self, "오류", err)
