from core.export.epub import is_chapter_heading
from core.gemini import compute_page_zscores, summarize_page_for_zscore
from core.gemini.markup import _has_repetition_loop


class OcrAnomaliesMixin:
    def _review_ocr_anomalies(self, transcriber, text_targets, text_meta, entries_map, failed_pages, ocr_ink_ratios=None, ocr_used_temps=None):
        ocr_ink_ratios = ocr_ink_ratios or {}
        ocr_used_temps = ocr_used_temps or {}
        z_records = []
        for page_no, img_or_fn in text_targets:
            entry = entries_map.get(page_no)
            if page_no in failed_pages:
                z_records.append({"page_no": page_no, "ink_ratio": 0.05, "char_count": 0, "is_illustration_only": False, "is_heading_only": False, "has_loop": False})
            elif entry and entry.get("type") == "text":
                paras = entry.get("paragraphs", [])
                if page_no in ocr_ink_ratios:
                    plain = "".join(p.plain_text for p in paras)
                    clean_chars = len("".join(plain.split()))
                    non_empty = [p for p in paras if p.plain_text.strip() and not p.is_scene_break]
                    is_heading_only = bool(non_empty) and len(non_empty) <= 2 and all(is_chapter_heading(p) for p in non_empty)
                    z_records.append({
                        "page_no": page_no,
                        "ink_ratio": ocr_ink_ratios[page_no],
                        "char_count": clean_chars,
                        "is_illustration_only": False,
                        "is_heading_only": is_heading_only,
                        "has_loop": _has_repetition_loop(plain),
                    })
                else:
                    img = img_or_fn() if callable(img_or_fn) else img_or_fn
                    z_records.append(summarize_page_for_zscore(page_no, img, paras, False))
        z_records, _ = compute_page_zscores(z_records, self.opts.gemini_z_threshold)
        anomalies = [record for record in z_records if record["z_anomaly"] or record["page_no"] in failed_pages]
        if not anomalies:
            return
        self.log.emit(f"OCR 통계 검토: {len(anomalies)}페이지 확인 필요")
        total_anom = len(anomalies)
        self.progress_stage.emit(f"3/5 이상치 검토 (0/{total_anom})")
        self.progress.emit(0, total_anom)
        policy = self.opts.gemini_on_fail_action
        bulk_decision = None
        for idx, record in enumerate(anomalies, start=1):
            if self._cancelled:
                return
            page_no = record["page_no"]
            source_name, part_index, part, source_key, img_or_fn, fp = text_meta[page_no]
            target_img = img_or_fn() if callable(img_or_fn) else img_or_fn
            error = failed_pages.get(page_no, f"문자 수 통계 이상 (Z={record['z_score']})")
            current_entry = entries_map.get(page_no, {})
            current_text = self._paragraphs_to_editable_text(current_entry.get("paragraphs", []))
            retry_text = ""
            cur_page_temp = float(ocr_used_temps.get(page_no, self.opts.gemini_temperature))
            if self.opts.gemini_z_retry and page_no not in failed_pages:
                retry_start_temp = min(1.5, cur_page_temp + float(self.opts.gemini_temp_step))
                result_map, _ = transcriber.transcribe_batch_resilient([(page_no, target_img)], cancelled_fn=lambda: self._cancelled, log_cb=self.log.emit, start_temp=retry_start_temp, max_attempts=1)
                self._emit_token_usage(transcriber)
                retry_result = result_map.get(page_no)
                if retry_result and retry_result.paragraphs:
                    retry_text = self._paragraphs_to_editable_text(retry_result.paragraphs)
            cur_model = self.opts.gemini_model
            while True:
                if self._cancelled:
                    return
                is_bulk_replay = bulk_decision is not None
                decision = dict(bulk_decision) if is_bulk_replay else {"action": policy}
                if policy == "ask" and not is_bulk_replay:
                    decision = self._ask_user_review({
                        "page_no": page_no,
                        "source_name": source_name,
                        "image": target_img,
                        "reason": error,
                        "actual_chars": record.get("char_count", 0),
                        "expected_chars": record.get("expected_chars", 0),
                        "z_score": record.get("z_score", 0),
                        "current_text": current_text,
                        "current_model": cur_model,
                        "current_temp": cur_page_temp,
                        "retry_candidate_text": retry_text,
                    })
                    if decision.get("apply_all"):
                        bulk_decision = {"action": decision.get("action", "keep_edited"), "model": decision.get("model"), "temperature": decision.get("temperature")}
                action = decision.get("action", "keep_edited")
                if action == "cancel":
                    self._cancelled = True
                    return
                if action == "retry_gemini":
                    retry_temp = float(decision.get("temperature", cur_page_temp))
                    retry_model = decision.get("model") or cur_model
                    result_map, retry_failures = transcriber.transcribe_batch_resilient([(page_no, target_img)], cancelled_fn=lambda: self._cancelled, log_cb=self.log.emit, start_temp=retry_temp, model_override=retry_model, max_attempts=1)
                    self._emit_token_usage(transcriber)
                    result = result_map.get(page_no)
                    if result and result.paragraphs:
                        entries_map[page_no] = self._make_text_entry(page_no, source_name, part_index, part, source_key, result.paragraphs, fingerprint=fp)
                        plain = "".join(p.plain_text for p in result.paragraphs)
                        clean_chars = len("".join(plain.split()))
                        non_empty = [p for p in result.paragraphs if p.plain_text.strip() and not p.is_scene_break]
                        record["char_count"] = clean_chars
                        record["is_heading_only"] = bool(non_empty) and len(non_empty) <= 2 and all(is_chapter_heading(p) for p in non_empty)
                        record["has_loop"] = _has_repetition_loop(plain)
                        if result.ink_ratio >= 0.0:
                            record["ink_ratio"] = result.ink_ratio
                        z_records, _ = compute_page_zscores(z_records, self.opts.gemini_z_threshold)
                        record = next((r for r in z_records if r["page_no"] == page_no), record)
                        if record.get("z_anomaly"):
                            self.log.emit(f"[OCR 재시도 후에도 통계 이상] p{page_no}: {record['char_count']}자 (Z={record['z_score']})")
                            if policy != "ask" or bulk_decision is not None:
                                break
                            error = f"재시도 후에도 문자 수 통계 이상 (Z={record['z_score']})"
                            current_text = self._paragraphs_to_editable_text(result.paragraphs)
                            cur_model = retry_model
                            cur_page_temp = retry_temp
                            continue
                        self.log.emit(f"[OCR 재시도 반영 · 정상화] p{page_no} ({record['char_count']}자, Z={record['z_score']})")
                        break
                    retry_err = retry_failures.get(page_no, "결과 없음")
                    self.log.emit(f"[OCR 재시도 실패] p{page_no}: {retry_err}")
                    if policy != "ask" or bulk_decision is not None:
                        break
                    error = f"재시도 실패 ({retry_err})"
                    cur_model = retry_model
                    cur_page_temp = retry_temp
                    if decision.get("edited_text") is not None:
                        current_text = decision["edited_text"]
                    continue
                elif action == "illustration":
                    self.log.emit(f"[사용자 분류] p{page_no}: 삽화로 저장")
                    entries_map[page_no] = self._make_illustration_entry(
                        page_no, source_name, part_index, part, source_key, "사용자 미리보기/검수 지정 삽화", raw_image=target_img, fingerprint=fp
                    )
                    break
                elif action == "skip":
                    entries_map.pop(page_no, None)
                    break
                elif decision.get("edited_text") is not None and not is_bulk_replay:
                    paragraphs = self._editable_text_to_paragraphs(decision["edited_text"])
                    entries_map[page_no] = self._make_text_entry(page_no, source_name, part_index, part, source_key, paragraphs, fingerprint=fp)
                    break
                else:
                    self.log.emit(f"[기존 OCR 유지] p{page_no}")
                    break
            self.progress_stage.emit(f"3/5 이상치 검토 ({idx}/{total_anom})")
            self.progress.emit(idx, total_anom)
