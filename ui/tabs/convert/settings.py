from pathlib import Path
from typing import Dict

from PySide6.QtWidgets import QFileDialog, QLabel

from core.vision.image_utils import image_fingerprint, list_images_in_folder
from core.vision.novel_detector import SplitPart
from core.config.paths import OUT_IMG
from ui.dialogs.settings_dialog import AdvancedSettingsDialog
from ui.workers.preview_worker import FolderModeWorker


class SettingsMixin():
    def _set_status_label(self, label: QLabel, obj_name: str, text: str):
        label.setObjectName(obj_name)
        label.setText(text)
        label.style().unpolish(label)
        label.style().polish(label)

    def _browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "원본 폴더 선택", str(OUT_IMG))
        if not folder:
            return
        self.input_edit.setText(folder)
        in_path = Path(folder)
        self.book_title_edit.setText(in_path.name)
        self._cancel_worker_attr("_analysis_worker")
        self._cancel_worker_attr("_preview_worker")
        self._cancel_worker_attr("_preview_search_worker")
        self._cancel_worker_attr("_folder_mode_worker")
        self._analysis_cache = {}
        self._analysis_cache_key = None
        self._last_resolved_file_idx = -1
        self._last_resolved_parts = []
        self._cur_file_idx = 0
        self._cur_sub_idx = 0
        self._folder_mode_req_id = getattr(self, "_folder_mode_req_id", 0) + 1
        req_id = self._folder_mode_req_id
        self._set_status_label(self.lbl_preview_type, "statusMute", "폴더 이미지 및 형식 분석 중…")
        worker = FolderModeWorker(
            req_id,
            in_path,
            str(self.adv.get("illust_sensitivity", "normal")),
            self,
        )
        worker.completed.connect(self._on_folder_mode_detected)
        self._track_bg_worker(worker)
        self._folder_mode_worker = worker
        worker.start()

    def _on_folder_mode_detected(self, req_id: int, folder_str: str, files: list, mode: str):
        if req_id != getattr(self, "_folder_mode_req_id", 0):
            return
        cur_input = self.input_edit.text().strip()
        if not cur_input or Path(cur_input) != Path(folder_str):
            return
        self._preview_files = list(files)
        self._cur_file_idx = 0
        self._cur_sub_idx = 0
        self._last_resolved_file_idx = -1
        self._last_resolved_parts = []
        self._analysis_cache = {}
        self._analysis_cache_key = None
        if self._preview_files:
            if mode == "novel":
                target = "novel"
            else:
                current = str(self.format_combo.currentData())
                target = current if current.startswith("manga") else "manga_pdf"
            idx = self.format_combo.findData(target)
            if idx >= 0 and idx != self.format_combo.currentIndex():
                self.format_combo.setCurrentIndex(idx)
                return
        self._restart_analysis()
        self._refresh_preview()

    def _open_advanced_settings(self, initial_tab: int = 1):
        dlg = AdvancedSettingsDialog(self.collect_settings(), parent=self, initial_tab=initial_tab)
        if dlg.exec():
            self.adv.update(dlg.get_values())
            self.settingsChanged.emit()
            self._schedule_analysis()
            self._refresh_preview()

    def _open_gemini_settings(self):
        self._open_advanced_settings(initial_tab=1)

    def _is_novel(self) -> bool:
        return self.format_combo.currentData() == "novel"

    def _manga_format(self) -> str:
        return "zip" if self.format_combo.currentData() == "manga_zip" else "pdf"

    def _on_mode_changed(self, *_):
        is_novel = self._is_novel()
        self.novel_box.setVisible(is_novel)
        self.manga_box.setVisible(not is_novel)
        self.btn_cover_crop.setEnabled(not is_novel and self.chk_cover_crop.isChecked())
        self.btn_cover_auto.setEnabled(not is_novel)
        self.btn_epub_only.setVisible(is_novel)
        self.btn_find_text.setEnabled(is_novel)
        self.btn_next_illustration.setEnabled(is_novel)
        self.chk_preview_illustration.setVisible(is_novel)
        self.chk_preview_illust_trim.setVisible(False)
        self.btn_preview_unmerge.setVisible(False)
        self.btn_preview_merge.setVisible(False)
        self.chk_preview_side_crop.setVisible(False)
        self.btn_side_crop_apply.setVisible(False)
        self.btn_side_crop_cancel.setVisible(False)
        self.chk_trim.setEnabled(is_novel)
        self.chk_small_illust.setEnabled(is_novel)
        self.chk_trim_before_illust.setEnabled(is_novel)
        self.chk_remove_header.setEnabled(is_novel)
        header_on = is_novel and self.chk_remove_header.isChecked()
        self.combo_header_cut.setEnabled(header_on)
        self.spin_header_top.setEnabled(header_on)
        self.chk_crop_illust.setEnabled(header_on)
        self.preview_widget.set_cutline_enabled(header_on and str(self.combo_header_cut.currentData()) != "off")
        self.settingsChanged.emit()
        self._schedule_analysis()
        self._refresh_preview()

    def _on_preprocess_changed(self):
        on = self.chk_split.isChecked()
        self.chk_split_skip_first.setEnabled(on)
        self.chk_split_large.setEnabled(on)
        self.settingsChanged.emit()
        self._schedule_analysis()
        self._refresh_preview()

    def _on_header_opts_changed(self):
        on = self._is_novel() and self.chk_remove_header.isChecked()
        self.combo_header_cut.setEnabled(on)
        self.spin_header_top.setEnabled(on)
        self.chk_crop_illust.setEnabled(on)
        self.preview_widget.set_top_pct(self.spin_header_top.value())
        self.preview_widget.set_cutline_enabled(on and str(self.combo_header_cut.currentData()) != "off")
        self.settingsChanged.emit()
        self._schedule_analysis()
        self._refresh_preview()

    def _on_header_spin_changed(self):
        self.preview_widget.set_top_pct(self.spin_header_top.value())
        self.settingsChanged.emit()
        self._schedule_analysis()
        self._refresh_preview()

    def _classification_key(self, file_idx: int, part_idx: int, part: SplitPart) -> str:
        fp = part.fingerprint
        if not fp:
            img = self._part_image(part)
            fp = image_fingerprint(img) if img is not None else ""
            part.fingerprint = fp
        return f"{self._preview_files[file_idx].name}::{part_idx}::{fp}"

    def collect_settings(self) -> Dict:
        return {
            **self.adv,
            "input_dir": self.input_edit.text().strip(),
            "mode": "novel" if self._is_novel() else "manga",
            "manga_format": "pdf" if self._manga_format() == "pdf" else "zip",
            "book_title": self.book_title_edit.text().strip(),
            "split_enabled": self.chk_split.isChecked(),
            "split_skip_first": self.chk_split_skip_first.isChecked(),
            "split_large_images": self.chk_split_large.isChecked(),
            "trim_enabled": self.chk_trim.isChecked(),
            "small_illust_enabled": self.chk_small_illust.isChecked(),
            "trim_before_illust_detect": self.chk_trim_before_illust.isChecked(),
            "remove_text_header": self.chk_remove_header.isChecked(),
            "header_cut_mode": str(self.combo_header_cut.currentData()),
            "crop_illustrations": self.chk_crop_illust.isChecked(),
            "header_top_pct": self.spin_header_top.value(),
            "cover_crop_enabled": self.chk_cover_crop.isChecked(),
            "cover_crop_rect": list(self._cover_crop_rect) if self._cover_crop_rect else None,
            "classification_overrides": dict(self._classification_overrides),
            "illust_trim_overrides": dict(self._illust_trim_overrides),
            "illust_side_crops": dict(self._illust_side_crops),
            "illust_no_merge": dict(self._illust_no_merge),
            "no_auto_separate": dict(self._no_auto_separate),
        }

    def apply_settings(self, s: Dict):
        saved_input = str(s.get("input_dir", "")).strip()
        if saved_input:
            self.input_edit.setText(saved_input)
            saved_path = Path(saved_input)
            if saved_path.is_dir():
                self._preview_files = list_images_in_folder(saved_path)
                self.book_title_edit.setText(str(s.get("book_title", "")).strip() or saved_path.name)
        if s.get("mode") == "manga":
            self.format_combo.setCurrentIndex(2 if s.get("manga_format") == "zip" else 1)
        else:
            self.format_combo.setCurrentIndex(0)

        self.chk_split.setChecked(bool(s.get("split_enabled", True)))
        self.chk_split_skip_first.setChecked(bool(s.get("split_skip_first", True)))
        self.chk_split_large.setChecked(bool(s.get("split_large_images", False)))
        self.chk_trim.setChecked(bool(s.get("trim_enabled", True)))
        self.chk_small_illust.setChecked(bool(s.get("small_illust_enabled", True)))
        self.chk_trim_before_illust.setChecked(bool(s.get("trim_before_illust_detect", True)))

        self.chk_remove_header.setChecked(bool(s.get("remove_text_header", True)))
        idx = self.combo_header_cut.findData(s.get("header_cut_mode", "auto"))
        if idx >= 0:
            self.combo_header_cut.setCurrentIndex(idx)
        self.chk_crop_illust.setChecked(bool(s.get("crop_illustrations", False)))
        self.spin_header_top.setValue(float(s.get("header_top_pct", 3.0)))
        saved_crop = s.get("cover_crop_rect")
        self._cover_crop_rect = tuple(saved_crop) if saved_crop and len(saved_crop) == 4 else None
        self.chk_cover_crop.setChecked(bool(s.get("cover_crop_enabled", False) and self._cover_crop_rect))
        self._classification_overrides = dict(s.get("classification_overrides", {}) or {})
        self._illust_trim_overrides = dict(s.get("illust_trim_overrides", {}) or {})
        self._illust_side_crops = dict(s.get("illust_side_crops", {}) or {})
        self._illust_no_merge = dict(s.get("illust_no_merge", {}) or {})
        self._no_auto_separate = dict(s.get("no_auto_separate", {}) or {})
        self._refresh_preview()