import hashlib
import json
from pathlib import Path
import shutil
from typing import Dict, List

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from core.image_utils import (
    crop_normalized_rect,
    detect_illustration_bounds,
    image_fingerprint,
    is_blank_image,
    load_image_rgb,
    save_tmp_image,
)
from core.novel_detector import SplitPart
from core.page_pipeline import compute_base_parts, default_illust_trim_enabled, render_illustration_image
from core.paths import DIR_TMP
from ui.dialogs.cover_crop_dialog import CoverCropDialog
from ui.workers.analysis_worker import PageAnalysisWorker


class PreviewMixin():
    def _preview_cache_root(self) -> Path:
        return DIR_TMP / "preview"

    def _preview_cache_dir(self, params_key: str) -> Path:
        digest = hashlib.sha1(params_key.encode("utf-8")).hexdigest()[:12]
        cache_dir = self._preview_cache_root() / digest
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _cleanup_preview_cache(self, keep_dir: Path = None):
        root = self._preview_cache_root()
        if not root.is_dir():
            return
        for child in root.iterdir():
            if keep_dir is not None and child == keep_dir:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    @staticmethod
    def _part_image(part: SplitPart):
        if part.image is not None:
            return part.image
        if part.image_path is not None and Path(part.image_path).is_file():
            return load_image_rgb(Path(part.image_path))
        return None

    def _part_is_blank(self, part: SplitPart) -> bool:
        if part.is_blank is not None:
            return bool(part.is_blank)
        img = self._part_image(part)
        if img is None:
            return True
        blank = is_blank_image(img)
        part.is_blank = blank
        return blank

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
        }

    def _refresh_preview(self):
        total_files = len(self._preview_files)
        if total_files == 0:
            self.spin_page_input.setRange(0, 0)
            self.spin_page_input.setValue(0)
            self.lbl_total_pages.setText("/ 0")
            self.chk_preview_illust_trim.setVisible(False)
            self._set_status_label(self.lbl_preview_type, "statusMute", "폴더를 선택하세요")
            self.preview_widget.set_image(None)
            return

        self.spin_page_input.blockSignals(True)
        self.spin_page_input.setRange(1, total_files)
        self.spin_page_input.setValue(self._cur_file_idx + 1)
        self.lbl_total_pages.setText(f"/ {total_files}")
        self.spin_page_input.blockSignals(False)

        self._cur_file_idx = max(0, min(self._cur_file_idx, total_files - 1))
        parts = self._resolve_file_parts(self._cur_file_idx)
        self._cur_sub_idx = max(0, min(self._cur_sub_idx, len(parts) - 1))

        part = parts[self._cur_sub_idx]
        fname = self._preview_files[self._cur_file_idx].name
        sub_label = f" [{self._cur_sub_idx + 1}/{len(parts)}]" if len(parts) > 1 else ""

        self.chk_preview_illustration.blockSignals(True)
        self.chk_preview_illustration.setChecked(bool(part.is_illustration))
        self.chk_preview_illustration.blockSignals(False)
        self.chk_preview_illustration.setVisible(self._is_novel())

        part_img = self._part_image(part)
        if part_img is None or self._part_is_blank(part):
            self.chk_preview_illust_trim.setVisible(False)
            self.preview_widget.set_hover_only(False)
            self.preview_widget.set_cutline_enabled(False)
            self.preview_widget.set_image(part_img)
            self._set_status_label(self.lbl_preview_type, "statusMute", f"{fname}{sub_label} · 빈 페이지")
            return
        if not self._is_novel():
            self.chk_preview_illustration.setVisible(False)
            self.chk_preview_illust_trim.setVisible(False)
            self.preview_widget.set_hover_only(False)
            self.preview_widget.set_cutline_enabled(False)
            self.preview_widget.set_image(part_img)
            self._set_status_label(self.lbl_preview_type, "statusInfo", f"{fname}{sub_label} · 만화 · 원본 유지")
            return
        if part.is_illustration:
            trim_this = self._is_illust_trim_enabled(self._cur_file_idx, self._cur_sub_idx, part)
            self.chk_preview_illust_trim.blockSignals(True)
            self.chk_preview_illust_trim.setChecked(trim_this)
            self.chk_preview_illust_trim.blockSignals(False)
            self.chk_preview_illust_trim.setVisible(True)

            r_params = self._render_params()
            render_part = SplitPart(
                part_img,
                part.split_note,
                part.is_illustration,
                part.analysis_reason,
                header_cut_applied=part.header_cut_applied,
                detected_header_cut_y=part.detected_header_cut_y,
                is_mini_illust=part.is_mini_illust,
            )
            display_image = render_illustration_image(render_part, r_params, trim_override=trim_this)
            show_cut = r_params["remove_text_header"] and r_params["crop_illustrations"] and r_params["header_cut_mode"] != "off" and not part.header_cut_applied
            self.preview_widget.set_hover_only(True)
            self.preview_widget.set_cutline_enabled(show_cut)
            self.preview_widget.set_image(display_image, edit_image=part_img)
            self._set_status_label(self.lbl_preview_type, "statusWarn", f"{fname}{sub_label} · 삽화 ({part.analysis_reason})")
        else:
            self.chk_preview_illust_trim.setVisible(False)
            self.preview_widget.set_hover_only(False)
            show_cut = self.chk_remove_header.isChecked() and str(self.combo_header_cut.currentData()) != "off" and not part.header_cut_applied
            self.preview_widget.set_cutline_enabled(show_cut)
            self.preview_widget.set_image(part_img)
            self._set_status_label(self.lbl_preview_type, "statusOk", f"{fname}{sub_label} · 본문 텍스트")

    def _on_page_spin_changed(self, val: int):
        if val >= 1 and val <= len(self._preview_files):
            self._cur_file_idx = val - 1
            self._cur_sub_idx = 0
            self._refresh_preview()

    def _on_preview_wheel(self, direction: int):
        if not self._preview_files:
            return
        if direction < 0:
            self._prev_preview_page()
        else:
            self._next_preview_page()

    def _prev_preview_page(self):
        if not self._preview_files:
            return
        if self._cur_sub_idx > 0:
            self._cur_sub_idx -= 1
        elif self._cur_file_idx > 0:
            self._cur_file_idx -= 1
            prev_parts = self._resolve_file_parts(self._cur_file_idx)
            self._cur_sub_idx = max(0, len(prev_parts) - 1)
        self._refresh_preview()

    def _next_preview_page(self):
        if not self._preview_files:
            return
        cur_parts = self._resolve_file_parts(self._cur_file_idx)
        if self._cur_sub_idx + 1 < len(cur_parts):
            self._cur_sub_idx += 1
        elif self._cur_file_idx + 1 < len(self._preview_files):
            self._cur_file_idx += 1
            self._cur_sub_idx = 0
        self._refresh_preview()

    def _find_next_text_page(self):
        total = len(self._preview_files)
        if total == 0:
            return
        for f_offset in range(total):
            f_idx = (self._cur_file_idx + f_offset) % total
            parts = self._resolve_file_parts(f_idx)
            start_s = (self._cur_sub_idx + 1) if f_offset == 0 else 0
            for s_idx in range(start_s, len(parts)):
                part = parts[s_idx]
                if not self._part_is_blank(part) and not part.is_illustration:
                    self._cur_file_idx = f_idx
                    self._cur_sub_idx = s_idx
                    self._refresh_preview()
                    return
        QMessageBox.information(self, "안내", "본문 텍스트 페이지를 찾지 못했습니다.")

    def _find_next_illustration(self):
        if not self._preview_files:
            return
        total = len(self._preview_files)
        start_file, start_part = self._cur_file_idx, self._cur_sub_idx
        for file_offset in range(total):
            file_index = (start_file + file_offset) % total
            parts = self._resolve_file_parts(file_index)
            start_sub = start_part + 1 if file_offset == 0 else 0
            for part_index in range(start_sub, len(parts)):
                part = parts[part_index]
                if not self._part_is_blank(part) and part.is_illustration:
                    self._cur_file_idx = file_index
                    self._cur_sub_idx = part_index
                    self._refresh_preview()
                    return
        QMessageBox.information(self, "안내", "다음 삽화를 찾지 못했습니다.")

    def _on_preview_illustration_toggled(self, checked: bool):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._resolve_file_parts(self._cur_file_idx)
        if self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        key = self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
        self._classification_overrides[key] = bool(checked)
        self.adv["classification_overrides"] = dict(self._classification_overrides)
        self.settingsChanged.emit()
        self._refresh_preview()

    def _on_preview_illust_trim_toggled(self, checked: bool):
        if not self._preview_files or not self._is_novel():
            return
        parts = self._resolve_file_parts(self._cur_file_idx)
        if self._cur_sub_idx >= len(parts):
            return
        part = parts[self._cur_sub_idx]
        key = self._classification_key(self._cur_file_idx, self._cur_sub_idx, part)
        self._illust_trim_overrides[key] = bool(checked)
        self.adv["illust_trim_overrides"] = dict(self._illust_trim_overrides)
        self.settingsChanged.emit()
        self._refresh_preview()

    def _select_cover_crop(self):
        if not self._preview_files:
            QMessageBox.warning(self, "안내", "먼저 만화 이미지 폴더를 선택하세요.")
            return
        image = load_image_rgb(self._preview_files[0])
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

    def _auto_cover_crop(self):
        if not self._preview_files:
            QMessageBox.warning(self, "안내", "먼저 만화 이미지 폴더를 선택하세요.")
            return
        image = load_image_rgb(self._preview_files[0])
        bounds = detect_illustration_bounds(image, padding_ratio=0.0)
        x1, y1, x2, y2 = bounds
        if bounds == (0, 0, image.width, image.height):
            QMessageBox.information(self, "자동 자르기", "표지 바깥 여백을 확실하게 감지하지 못했습니다. 직접 영역 선택을 사용하세요.")
            return
        self._cover_crop_rect = (x1 / image.width, y1 / image.height, (x2 - x1) / image.width, (y2 - y1) / image.height)
        self.chk_cover_crop.blockSignals(True)
        self.chk_cover_crop.setChecked(True)
        self.chk_cover_crop.blockSignals(False)
        self.adv["cover_crop_enabled"] = True
        self.adv["cover_crop_rect"] = list(self._cover_crop_rect)
        self.settingsChanged.emit()
        self._refresh_preview()

    def _on_cover_crop_toggled(self, enabled: bool):
        self.btn_cover_crop.setEnabled(enabled and not self._is_novel())
        if enabled and not self._cover_crop_rect:
            self._select_cover_crop()
            if not self._cover_crop_rect:
                self.chk_cover_crop.blockSignals(True)
                self.chk_cover_crop.setChecked(False)
                self.chk_cover_crop.blockSignals(False)
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

    def _analysis_params(self) -> Dict:
        return {
            "split_enabled": self.chk_split.isChecked(),
            "split_skip_first": self.chk_split_skip_first.isChecked(),
            "split_only_wide": bool(self.adv.get("split_only_wide", True)),
            "split_large_images": self.chk_split_large.isChecked(),
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
        return json.dumps({"novel": self._is_novel(), **self._analysis_params()}, sort_keys=True)

    def _base_parts(self, file_idx: int) -> List[SplitPart]:
        params_key = self._params_key()
        cache_dir = self._preview_cache_dir(params_key)
        if not hasattr(self, "_analysis_cache") or self._analysis_cache_key != params_key:
            self._analysis_cache = {}
            self._analysis_cache_key = params_key
            self._cleanup_preview_cache(keep_dir=cache_dir)
        if file_idx in self._analysis_cache:
            return self._analysis_cache[file_idx]
        path = self._preview_files[file_idx]
        img = load_image_rgb(path)
        is_novel = self._is_novel()
        if not is_novel and file_idx == 0 and self.chk_cover_crop.isChecked() and self._cover_crop_rect:
            cropped = crop_normalized_rect(img, self._cover_crop_rect)
            parts = [SplitPart(cropped, "첫 장 표지 영역 자르기", True, "사용자 지정 표지 영역")]
        else:
            parts = compute_base_parts(img, file_idx == 0, is_novel, self._analysis_params())
        cached_parts = []
        for part_idx, part in enumerate(parts):
            fp = part.fingerprint or image_fingerprint(part.image)
            blank = part.is_blank if part.is_blank is not None else is_blank_image(part.image)
            out_path = cache_dir / f"{file_idx:05d}_{part_idx:02d}.png"
            save_tmp_image(part.image, out_path)
            cached_parts.append(
                SplitPart(
                    None,
                    part.split_note,
                    part.is_illustration,
                    part.analysis_reason,
                    header_cut_applied=part.header_cut_applied,
                    detected_header_cut_y=part.detected_header_cut_y,
                    is_mini_illust=part.is_mini_illust,
                    image_path=out_path,
                    fingerprint=fp,
                    is_blank=blank,
                )
            )
        self._analysis_cache[file_idx] = cached_parts
        return cached_parts

    def _restart_analysis(self):
        if not self._preview_files or not self._is_novel():
            return
        old = getattr(self, "_analysis_worker", None)
        if old is not None:
            try:
                old.cancel()
            except RuntimeError:
                pass
            self._analysis_worker = None
        params_key = self._params_key()
        cache_dir = self._preview_cache_dir(params_key)
        self._analysis_cache = {}
        self._analysis_cache_key = params_key
        self._cleanup_preview_cache(keep_dir=cache_dir)
        worker = PageAnalysisWorker(
            self._preview_files,
            self._analysis_params(),
            True,
            self._cur_file_idx,
            self,
            cache_dir=cache_dir,
        )
        worker.page_ready.connect(self._on_page_analyzed)
        worker.finished.connect(lambda w=worker: self._on_analysis_worker_finished(w))
        worker.finished.connect(worker.deleteLater)
        self._analysis_worker = worker
        worker.start()

    def _on_analysis_worker_finished(self, worker):
        if getattr(self, "_analysis_worker", None) is worker:
            self._analysis_worker = None

    def _schedule_analysis(self):
        if not hasattr(self, "_analysis_timer"):
            self._analysis_timer = QTimer(self)
            self._analysis_timer.setSingleShot(True)
            self._analysis_timer.timeout.connect(self._restart_analysis)
        self._analysis_timer.start(250)

    def _on_page_analyzed(self, index: int, parts):
        if getattr(self, "_analysis_cache_key", None) != self._params_key():
            return
        self._analysis_cache[index] = parts
        if index == self._cur_file_idx:
            self._refresh_preview()

    def _resolve_file_parts(self, file_idx: int) -> List[SplitPart]:
        parts = self._base_parts(file_idx)
        overrides = []
        for part_index, part in enumerate(parts):
            key = self._classification_key(file_idx, part_index, part)
            if key in self._classification_overrides:
                value = bool(self._classification_overrides[key])
                part = SplitPart(
                    part.image,
                    part.split_note,
                    value,
                    "사용자 지정 삽화" if value else "사용자 지정 본문",
                    header_cut_applied=part.header_cut_applied,
                    detected_header_cut_y=part.detected_header_cut_y,
                    is_mini_illust=part.is_mini_illust,
                    image_path=part.image_path,
                    fingerprint=part.fingerprint,
                    is_blank=part.is_blank,
                )
            overrides.append(part)
        return overrides