from PySide6.QtWidgets import QMessageBox

from core.vision.novel_detector import SplitPart
from core.vision.page_pipeline import render_illustration_image


class PreviewViewerMixin:
    def _refresh_preview(self):
        total_files = len(self._preview_files)
        if total_files == 0:
            self.spin_page_input.setRange(0, 0)
            self.spin_page_input.setValue(0)
            self.lbl_total_pages.setText("/ 0")
            self.chk_preview_illust_trim.setVisible(False)
            self.btn_preview_unmerge.setVisible(False)
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
            self.btn_preview_unmerge.setVisible(False)
            self.preview_widget.set_hover_only(False)
            self.preview_widget.set_cutline_enabled(False)
            self.preview_widget.set_image(part_img)
            self._set_status_label(self.lbl_preview_type, "statusMute", f"{fname}{sub_label} · 빈 페이지")
            return
        if not self._is_novel():
            self.chk_preview_illustration.setVisible(False)
            self.chk_preview_illust_trim.setVisible(False)
            self.btn_preview_unmerge.setVisible(False)
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
            self.btn_preview_unmerge.setVisible(part.split_note == "양면 삽화 병합")

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
            self.btn_preview_unmerge.setVisible(False)
            self.preview_widget.set_hover_only(False)
            show_cut = self.chk_remove_header.isChecked() and str(self.combo_header_cut.currentData()) != "off" and not part.header_cut_applied
            self.preview_widget.set_cutline_enabled(show_cut)
            self.preview_widget.set_image(part_img)
            self._set_status_label(self.lbl_preview_type, "statusOk", f"{fname}{sub_label} · 본문 텍스트")

    def _on_page_spin_changed(self, val: int):
        if 1 <= val <= len(self._preview_files):
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
