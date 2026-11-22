from difflib import SequenceMatcher

from core.config.paths import DIR_OUT
from core.export.epub import deduplicate_entries
from core.export.epub.text_utils import _plain_key
from core.export.exporters import export_light_novel, save_ocr_backup
from ui.workers.review.helpers import is_safe_content_correction, strip_for_diff


class ContentCheckWorkerMixin:
    def _run_content_review_passes(self, transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design, checks, content_checks):
        bulk_large_policy = None
        max_passes = max(1, min(3, int(self.opts.gemini_review_passes)))
        for pass_no in range(1, max_passes + 1):
            if self._cancelled:
                return ordered, chapters, True
            review_pages = []
            for entry in ordered:
                if entry.get("type") != "text":
                    continue
                text = self._paragraphs_to_editable_text(entry.get("paragraphs", []))
                if text.strip():
                    has_long_line = any(len(line.strip()) >= 110 for line in text.splitlines())
                    review_pages.append({
                        "page_no": int(entry.get("page_no", 0)),
                        "type": "text",
                        "needs_paragraph_split": has_long_line,
                        "text": text,
                    })
            if not review_pages:
                break
            batch_size = max(1, int(getattr(self.opts, "gemini_review_batch_size", 15)))
            est_batches = max(1, (len(review_pages) + batch_size - 1) // batch_size)
            self.progress_stage.emit(f"5/5 최종 내용 검수 {pass_no}/{max_passes} (0/{est_batches})")
            self.progress.emit(0, est_batches)
            self.log.emit(f"Gemini 최종 내용 검수 {pass_no}/{max_passes}: 본문 {len(review_pages)}페이지 · {', '.join(checks)}")

            def on_review_progress(done: int, total_b: int):
                self.progress_stage.emit(f"5/5 최종 내용 검수 {pass_no}/{max_passes} ({done}/{total_b})")
                self.progress.emit(done, total_b)
                self._emit_token_usage(transcriber)

            try:
                result = transcriber.review_epub_content(
                    review_pages,
                    content_checks,
                    cancelled_fn=lambda: self._cancelled,
                    max_concurrent=max(1, int(self.opts.gemini_max_concurrent)),
                    progress_cb=on_review_progress,
                    log_cb=self.log.emit,
                    original_loader=original_loader,
                    batch_size=batch_size,
                )
                self._emit_token_usage(transcriber)
            except InterruptedError:
                return ordered, chapters, True
            except Exception as exc:
                self.log.emit(f"[Gemini 최종 내용 검수 실패] {exc}")
                break

            changed = 0
            by_page = {int(entry.get("page_no", 0)): entry for entry in ordered}
            for correction in result.get("corrections", []):
                page_no = int(correction.get("page_no", 0))
                entry = by_page.get(page_no)
                if not entry or entry.get("type") != "text":
                    continue
                old_paras = entry.get("paragraphs", [])
                old_text = self._paragraphs_to_editable_text(old_paras)
                new_text = str(correction.get("corrected_text", "")).strip()
                if not new_text or new_text == old_text.strip():
                    continue
                if not is_safe_content_correction(old_text, new_text):
                    if bulk_large_policy == "keep":
                        self.log.emit(f"[수정 제외 · 사용자 유지 선택] p{page_no}")
                        continue
                    if bulk_large_policy != "apply":
                        old_pl = strip_for_diff(old_text)
                        new_pl = strip_for_diff(new_text)
                        sim = SequenceMatcher(None, old_pl, new_pl).ratio() * 100.0
                        reason_msg = str(correction.get("reason", "")).strip()
                        if old_pl and len(new_pl) < len(old_pl) * 0.45:
                            reason_msg = "수정안이 원문보다 훨씬 짧음(부분 발췌 의심) | " + reason_msg
                        decision = self._ask_user_correction_preview({
                            "page_no": page_no,
                            "image": original_loader(page_no),
                            "old_text": old_text,
                            "new_text": new_text,
                            "reason": reason_msg,
                            "similarity": sim,
                        })
                        act = decision.get("action", "keep")
                        if act == "cancel":
                            self._cancelled = True
                            return ordered, chapters, True
                        if decision.get("apply_all"):
                            bulk_large_policy = act
                        if act != "apply":
                            self.log.emit(f"[수정 제외 · 사용자 유지 선택] p{page_no}")
                            continue
                        edited = str(decision.get("edited_text", "")).strip()
                        if edited:
                            new_text = edited
                        self.log.emit(f"[대량 수정 사용자 승인] p{page_no}")
                    else:
                        self.log.emit(f"[대량 수정 일괄 승인] p{page_no}")

                prev_heading_map = {
                    _plain_key(p.plain_text): (p.is_heading, p.heading_level, p.block_type, p.is_toc_candidate, p.is_bic_candidate, p.is_toc_entry)
                    for p in old_paras
                    if p.plain_text.strip()
                }
                new_paras = self._editable_text_to_paragraphs(new_text)
                for np_obj in new_paras:
                    k = _plain_key(np_obj.plain_text)
                    if k in prev_heading_map:
                        ih, hl, bt, itc, ibc, ite = prev_heading_map[k]
                        if ih and not np_obj.is_heading:
                            np_obj.is_heading = ih
                            np_obj.heading_level = hl
                            np_obj.block_type = bt
                        if itc and not np_obj.is_bic_candidate:
                            np_obj.is_toc_candidate = True
                        if ibc and not np_obj.is_toc_candidate:
                            np_obj.is_bic_candidate = True
                        if ite:
                            np_obj.is_toc_entry = True
                            np_obj.block_type = bt
                entry["paragraphs"] = new_paras
                entry["ocr_error"] = ""
                changed += 1
                reason = str(correction.get("reason", "")).strip()
                self.log.emit(f"[Gemini 수정 반영] p{page_no}" + (f": {reason}" if reason else ""))
            for issue in result.get("issues", []):
                self.log.emit(f"[Gemini 검수 의견] {issue}")
            if not changed:
                self.log.emit("Gemini 최종 내용 검수: 자동 수정할 만큼 명확한 오류가 발견되지 않았습니다.")
                break
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
            self.log.emit(f"최종 검수 수정 적용 완료: {changed}페이지 수정 · EPUB 재생성")
            if self._cancelled:
                return ordered, chapters, True
        return ordered, chapters, False
