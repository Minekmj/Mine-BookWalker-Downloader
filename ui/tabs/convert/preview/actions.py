import json
from typing import Dict

from PySide6.QtWidgets import QMessageBox

from core.vision.novel_detector import SplitPart
from core.vision.page_pipeline import default_illust_trim_enabled
from ui.dialogs.cover_crop_dialog import CoverCropDialog
from ui.workers.preview_worker import CoverCropWorker


class PreviewActionsMixin:
    def _is_illust_trim_enabled(self, file_idx: int, part_idx: int, part: SplitPart) -> bool:
        key = self._classification_key(file_idx, part_idx, part)
        if key in self._illust_trim_overrides:
            return bool(self._illust_trim_overrides[key])
        return default_illust_trim_enabled(part, {"trim_enabled": self.chk_trim.isChecked()})

    def _render_params(self) -> Dict:
        return {
            "remove_text_header": self.chk_remove_header.isChecked(),
            "crop_illustrations": self.chk_crop_illust.isChecked(),
            "header_top_pct": self.spin_header_top.value(),
            "header_cut_mode": str(self.combo_header_cut.currentData()),
            "trim_enabled": self.chk_trim.isChecked(),
            "trim_top": bool(self.adv.get("trim_top", True)),
            "trim_bottom": bool(self.adv.get("trim_bottom", True)),
            "trim_left": bool(self.adv.get("trim_left", True)),
            "trim_right": bool(self.adv.get("trim_right", True)),
            "white_threshold": int(self.adv.get("white_threshold", 240)),
            "trim_padding": int(self.adv.get("trim_padding", 1)),
            "trim_extra_px": int(self.adv.get("trim_extra_px", 0)),
        }

    def _analysis_params(self) -> Dict:
        return {
            "split_enabled": self.chk_split.isChecked(),
            "split_skip_first": self.chk_split_skip_first.isChecked(),
            "split_only_wide": bool(self.adv.get("split_only_wide", True)),
            "split_large_images": self.chk_split_large.isChecked(),
            "auto_separate_disabled": False,
            "no_auto_separate": dict(self._no_auto_separate),
            "read_direction": "RTL",
            "illust_sensitivity": str(self.adv.get("illust_sensitivity", "normal")),
            "remove_text_header": self.chk_remove_header.isChecked(),
            "header_top_pct": self.spin_header_top.value(),
            "header_cut_mode": str(self.combo_header_cut.currentData()),
            "footer_bottom_pct": 0.0,
            "small_illust_enabled": self.chk_small_illust.isChecked(),
            "trim_before_illust_detect": self.chk_trim_before_illust.isChecked(),
            "white_threshold": int(self.adv.get("white_threshold", 240)),
        }

    def _params_key(self) -> str:
        return json.dumps({"input_dir": self.input_edit.text().strip(), "novel": self._is_novel(), "no_auto_separate": self._no_auto_separate, **self._analysis_params()}, sort_keys=True)

    def _current_resolved_parts(self):
        if getattr(self, "_last_resolved_file_idx", -1) == self._cur_file_idx and getattr(self, "_last_resolved_parts", None):
            return self._last_resolved_parts
        return getattr(self, "_analysis_cache", {}).get(self._cur_file_idx)

    def _on_preview_illustration_toggled(self, checked: bool):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._current_resolved_parts()
        if not parts or self._cur_sub_idx < 0 or self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        if part.split_note == "양면 삽화 병합" and not checked:
            base_parts = getattr(self, "_analysis_cache", {}).get(self._cur_file_idx) or parts
            removed = False
            for idx, bp in enumerate(base_parts):
                bkey = self._classification_key(self._cur_file_idx, idx, bp)
                if self._classification_overrides.get(bkey) is True:
                    del self._classification_overrides[bkey]
                    removed = True
            if not removed:
                for idx, bp in enumerate(base_parts):
                    bkey = self._classification_key(self._cur_file_idx, idx, bp)
                    self._classification_overrides[bkey] = False
        else:
            key = self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
            self._classification_overrides[key] = bool(checked)
        self.adv["classification_overrides"] = dict(self._classification_overrides)
        self.settingsChanged.emit()
        self._refresh_preview()

    def _on_preview_unmerge_clicked(self):
        if not self._preview_files or not self._is_novel():
            return
        fname = self._preview_files[self._cur_file_idx].name
        self._illust_no_merge[fname] = True
        self.adv["illust_no_merge"] = dict(self._illust_no_merge)
        self.settingsChanged.emit()
        self._refresh_preview()

    def _on_preview_merge_clicked(self):
        if not self._preview_files or not self._is_novel():
            return
        fname = self._preview_files[self._cur_file_idx].name
        self._no_auto_separate[fname] = True
        self.adv["no_auto_separate"] = dict(self._no_auto_separate)
        self.settingsChanged.emit()
        self._cur_sub_idx = 0
        self._restart_analysis()
        self._refresh_preview()

    def _on_preview_illust_trim_toggled(self, checked: bool):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._current_resolved_parts()
        if not parts or self._cur_sub_idx < 0 or self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        key = self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
        self._illust_trim_overrides[key] = bool(checked)
        self.adv["illust_trim_overrides"] = dict(self._illust_trim_overrides)
        self.settingsChanged.emit()
        self._refresh_preview()

    def _start_cover_crop_worker(self, action_mode: str):
        self._cover_crop_req_id = getattr(self, "_cover_crop_req_id", 0) + 1
        req_id = self._cover_crop_req_id
        self._cancel_worker_attr("_cover_crop_worker")
        worker = CoverCropWorker(req_id, action_mode, self._preview_files[0], self)
        worker.completed.connect(self._on_cover_crop_worker_completed)
        self._track_bg_worker(worker)
        self._cover_crop_worker = worker
        worker.start()

    def _on_cover_crop_worker_completed(self, req_id: int, action_mode: str, image, bounds):
        if req_id != getattr(self, "_cover_crop_req_id", 0):
            return
        if not self._preview_files or image is None:
            return
        if action_mode == "select":
            dialog = CoverCropDialog(image, self)
            if dialog.exec():
                self._cover_crop_rect = tuple(dialog.selected_rect)
                self.chk_cover_crop.blockSignals(True)
                self.chk_cover_crop.setChecked(True)
                self.chk_cover_crop.blockSignals(False)
                self.adv["cover_crop_enabled"] = True
                self.adv["cover_crop_rect"] = list(self._cover_crop_rect)
                self.settingsChanged.emit()
                self._refresh_preview()
            elif self.chk_cover_crop.isChecked() and not self._cover_crop_rect:
                self.chk_cover_crop.blockSignals(True)
                self.chk_cover_crop.setChecked(False)
                self.chk_cover_crop.blockSignals(False)
        elif action_mode == "auto":
            if bounds is None or bounds == (0, 0, image.width, image.height):
                self._refresh_preview()
                QMessageBox.information(self, "자동 자르기", "표지 바깥 여백을 확실하게 감지하지 못했습니다. 직접 영역 선택을 사용하세요.")
                return
            x1, y1, x2, y2 = bounds
            self._cover_crop_rect = (x1 / image.width, y1 / image.height, (x2 - x1) / image.width, (y2 - y1) / image.height)
            self.chk_cover_crop.blockSignals(True)
            self.chk_cover_crop.setChecked(True)
            self.chk_cover_crop.blockSignals(False)
            self.adv["cover_crop_enabled"] = True
            self.adv["cover_crop_rect"] = list(self._cover_crop_rect)
            self.settingsChanged.emit()
            self._refresh_preview()

    def _select_cover_crop(self):
        if not self._preview_files:
            QMessageBox.warning(self, "안내", "먼저 만화 이미지 폴더를 선택하세요.")
            return
        self._start_cover_crop_worker("select")

    def _auto_cover_crop(self):
        if not self._preview_files:
            QMessageBox.warning(self, "안내", "먼저 만화 이미지 폴더를 선택하세요.")
            return
        self._set_status_label(self.lbl_preview_type, "statusMute", "표지 여백 자동 감지 중…")
        self._start_cover_crop_worker("auto")

    def _on_cover_crop_toggled(self, enabled: bool):
        self.btn_cover_crop.setEnabled(enabled and not self._is_novel())
        if enabled and not self._cover_crop_rect:
            self._select_cover_crop()
            return
        self.adv["cover_crop_enabled"] = bool(enabled)
        self.adv["cover_crop_rect"] = list(self._cover_crop_rect) if self._cover_crop_rect else None
        self.settingsChanged.emit()
        self._refresh_preview()

    def _on_preview_cutline_dragged(self, top_pct: float):
        self.spin_header_top.blockSignals(True)
        self.spin_header_top.setValue(top_pct)
        self.spin_header_top.blockSignals(False)
        self.settingsChanged.emit()

    def _on_preview_side_crop_toggled(self, checked: bool):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._current_resolved_parts()
        if not parts or self._cur_sub_idx < 0 or self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        key = part.side_crop_origin_key or self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
        saved = self._illust_side_crops.get(key)
        if checked:
            if saved and len(saved) == 2:
                self._side_crop_pending = (float(saved[0]), float(saved[1]))
                if part.side_crop_origin_key and float(saved[1]) > 0.0:
                    self._cur_sub_idx = max(0, self._cur_sub_idx - 1)
            else:
                self._side_crop_pending = (0.0, 0.0)
            self._side_crop_editing = True
        else:
            self._side_crop_editing = False
            if saved and len(saved) == 2 and float(saved[1]) > 0.0:
                self._cur_sub_idx += 1
        self._refresh_preview()

    def _on_preview_side_crop_dragged(self, left_pct: float, right_pct: float):
        self._side_crop_pending = (float(left_pct), float(right_pct))

    def _on_side_crop_apply(self):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._current_resolved_parts()
        if not parts or self._cur_sub_idx < 0 or self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        key = self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
        lp, rp = self._side_crop_pending
        if lp > 0.0 or rp > 0.0:
            self._illust_side_crops[key] = [lp, rp]
            if rp > 0.0:
                self._cur_sub_idx += 1
        else:
            self._illust_side_crops.pop(key, None)
        self.adv["illust_side_crops"] = dict(self._illust_side_crops)
        self._side_crop_editing = False
        self.settingsChanged.emit()
        self._refresh_preview()

    def _on_side_crop_cancel(self):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._current_resolved_parts()
        if not parts or self._cur_sub_idx < 0 or self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        key = part.side_crop_origin_key or self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
        was_split = bool(part.side_crop_origin_key)
        old_saved = self._illust_side_crops.pop(key, None)
        if was_split and old_saved and len(old_saved) == 2 and float(old_saved[1]) > 0.0:
            self._cur_sub_idx = max(0, self._cur_sub_idx - 1)
        self.adv["illust_side_crops"] = dict(self._illust_side_crops)
        self._side_crop_pending = (0.0, 0.0)
        self._side_crop_editing = False
        self.settingsChanged.emit()
        self._refresh_preview()
