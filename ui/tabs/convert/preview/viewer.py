from PySide6.QtWidgets import QMessageBox


class PreviewViewerMixin:
    def _hide_side_crop_controls(self):
        self.chk_preview_side_crop.setVisible(False)
        self.btn_side_crop_apply.setVisible(False)
        self.btn_side_crop_cancel.setVisible(False)
        self.preview_widget.set_side_crop_enabled(False)

    def _refresh_preview(self):
        total_files = len(self._preview_files)
        if total_files == 0:
            self._preview_req_id = getattr(self, "_preview_req_id", 0) + 1
            self._cancel_worker_attr("_preview_worker")
            self._last_resolved_file_idx = -1
            self._last_resolved_parts = []
            self.spin_page_input.setRange(0, 0)
            self.spin_page_input.setValue(0)
            self.lbl_total_pages.setText("/ 0")
            self.chk_preview_illust_trim.setVisible(False)
            self.btn_preview_unmerge.setVisible(False)
            self.btn_preview_merge.setVisible(False)
            self._hide_side_crop_controls()
            self._set_status_label(self.lbl_preview_type, "statusMute", "폴더를 선택하세요")
            self.preview_widget.set_image(None)
            return

        self._cur_file_idx = max(0, min(self._cur_file_idx, total_files - 1))
        self.spin_page_input.blockSignals(True)
        self.spin_page_input.setRange(1, total_files)
        self.spin_page_input.setValue(self._cur_file_idx + 1)
        self.lbl_total_pages.setText(f"/ {total_files}")
        self.spin_page_input.blockSignals(False)

        fname = self._preview_files[self._cur_file_idx].name
        self._set_status_label(self.lbl_preview_type, "statusMute", f"{fname} · 불러오는 중…")
        self._schedule_preview_render(self._cur_file_idx, self._cur_sub_idx)

    def _on_preview_rendered(self, req_id: int, payload: dict):
        if req_id != getattr(self, "_preview_req_id", 0):
            return
        total_files = len(self._preview_files)
        if total_files == 0:
            return

        file_idx = payload["file_idx"]
        if file_idx >= total_files:
            return

        params_key = payload["params_key"]
        base_parts = payload.get("base_parts")
        if base_parts is not None and getattr(self, "_analysis_cache_key", None) == params_key:
            self._analysis_cache[file_idx] = base_parts

        parts = payload["resolved_parts"]
        sub_idx = payload["sub_idx"]
        self._cur_file_idx = file_idx
        self._cur_sub_idx = sub_idx
        self._last_resolved_file_idx = file_idx
        self._last_resolved_parts = parts

        part = parts[sub_idx]
        fname = self._preview_files[file_idx].name
        sub_label = f" [{sub_idx + 1}/{len(parts)}]" if len(parts) > 1 else ""

        self.chk_preview_illustration.blockSignals(True)
        self.chk_preview_illustration.setChecked(bool(part.is_illustration))
        self.chk_preview_illustration.blockSignals(False)
        self.chk_preview_illustration.setVisible(self._is_novel())

        display_qimg = payload.get("display_qimg")
        edit_qimg = payload.get("edit_qimg")
        is_blank = payload.get("is_blank", False)

        if display_qimg is None or display_qimg.isNull() or is_blank:
            self.chk_preview_illust_trim.setVisible(False)
            self.btn_preview_unmerge.setVisible(False)
            self.btn_preview_merge.setVisible(False)
            self._hide_side_crop_controls()
            self.preview_widget.set_hover_only(False)
            self.preview_widget.set_cutline_enabled(False)
            self.preview_widget.set_qimage(display_qimg)
            self._set_status_label(self.lbl_preview_type, "statusMute", f"{fname}{sub_label} · 빈 페이지")
            return

        if not self._is_novel():
            self.chk_preview_illustration.setVisible(False)
            self.chk_preview_illust_trim.setVisible(False)
            self.btn_preview_unmerge.setVisible(False)
            self.btn_preview_merge.setVisible(False)
            self._hide_side_crop_controls()
            self.preview_widget.set_hover_only(False)
            self.preview_widget.set_cutline_enabled(False)
            self.preview_widget.set_qimage(display_qimg)
            self._set_status_label(self.lbl_preview_type, "statusInfo", f"{fname}{sub_label} · 만화 · 원본 유지")
            return

        if part.is_illustration:
            trim_this = bool(payload.get("trim_this", False))
            self.chk_preview_illust_trim.blockSignals(True)
            self.chk_preview_illust_trim.setChecked(trim_this)
            self.chk_preview_illust_trim.blockSignals(False)
            self.chk_preview_illust_trim.setVisible(True)
            self.btn_preview_unmerge.setVisible(part.split_note == "양면 삽화 병합")
            self.btn_preview_merge.setVisible(part.split_note.startswith("본문·삽화 분할"))

            key = part.side_crop_origin_key or self._classification_key(file_idx, sub_idx, part)
            saved_crop = self._illust_side_crops.get(key)
            has_saved_crop = bool(saved_crop and len(saved_crop) == 2 and (float(saved_crop[0]) > 0.0 or float(saved_crop[1]) > 0.0))

            self.chk_preview_side_crop.blockSignals(True)
            self.chk_preview_side_crop.setChecked(self._side_crop_editing)
            self.chk_preview_side_crop.blockSignals(False)
            self.chk_preview_side_crop.setVisible(True)
            self.btn_side_crop_apply.setVisible(self._side_crop_editing)
            self.btn_side_crop_cancel.setVisible(self._side_crop_editing or has_saved_crop)

            if self._side_crop_editing:
                self.preview_widget.set_hover_only(False)
                self.preview_widget.set_cutline_enabled(False)
                self.preview_widget.set_side_crop_pcts(self._side_crop_pending[0], self._side_crop_pending[1])
                self.preview_widget.set_side_crop_enabled(True)
                self.preview_widget.set_qimage(display_qimg)
            else:
                r_params = self._render_params()
                show_cut = r_params["remove_text_header"] and r_params["crop_illustrations"] and r_params["header_cut_mode"] != "off" and not part.header_cut_applied
                self.preview_widget.set_side_crop_enabled(False)
                self.preview_widget.set_hover_only(True)
                self.preview_widget.set_cutline_enabled(show_cut)
                self.preview_widget.set_qimage(display_qimg, edit_qimg=edit_qimg)
            self._set_status_label(self.lbl_preview_type, "statusWarn", f"{fname}{sub_label} · 삽화 ({part.analysis_reason})")
        else:
            self.chk_preview_illust_trim.setVisible(False)
            self.btn_preview_unmerge.setVisible(False)
            self.btn_preview_merge.setVisible(part.split_note.startswith("본문·삽화 분할"))
            self._hide_side_crop_controls()
            self.preview_widget.set_hover_only(False)
            show_cut = self.chk_remove_header.isChecked() and str(self.combo_header_cut.currentData()) != "off" and not part.header_cut_applied
            self.preview_widget.set_cutline_enabled(show_cut)
            self.preview_widget.set_qimage(display_qimg)
            self._set_status_label(self.lbl_preview_type, "statusOk", f"{fname}{sub_label} · 본문 텍스트")

    def _on_page_spin_changed(self, val: int):
        if 1 <= val <= len(self._preview_files):
            self._side_crop_editing = False
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
        self._side_crop_editing = False
        if self._cur_sub_idx > 0:
            self._cur_sub_idx -= 1
        elif self._cur_file_idx > 0:
            self._cur_file_idx -= 1
            self._cur_sub_idx = -1
        self._refresh_preview()

    def _next_preview_page(self):
        if not self._preview_files:
            return
        self._side_crop_editing = False
        if getattr(self, "_last_resolved_file_idx", -1) == self._cur_file_idx and getattr(self, "_last_resolved_parts", None):
            cur_len = len(self._last_resolved_parts)
        else:
            cur_len = 1
        if 0 <= self._cur_sub_idx and self._cur_sub_idx + 1 < cur_len:
            self._cur_sub_idx += 1
        elif self._cur_file_idx + 1 < len(self._preview_files):
            self._cur_file_idx += 1
            self._cur_sub_idx = 0
        self._refresh_preview()

    def _find_next_text_page(self):
        if not self._preview_files:
            return
        self._last_search_target_illust = False
        self._start_preview_search(target_is_illustration=False)

    def _find_next_illustration(self):
        if not self._preview_files:
            return
        self._last_search_target_illust = True
        self._start_preview_search(target_is_illustration=True)

    def _on_preview_search_found(self, req_id: int, file_idx: int, sub_idx: int):
        if req_id != getattr(self, "_preview_search_req_id", 0):
            return
        self._side_crop_editing = False
        self._cur_file_idx = file_idx
        self._cur_sub_idx = sub_idx
        self._refresh_preview()

    def _on_preview_search_not_found(self, req_id: int):
        if req_id != getattr(self, "_preview_search_req_id", 0):
            return
        self._refresh_preview()
        if getattr(self, "_last_search_target_illust", True):
            QMessageBox.information(self, "안내", "다음 삽화를 찾지 못했습니다.")
        else:
            QMessageBox.information(self, "안내", "본문 텍스트 페이지를 찾지 못했습니다.")
