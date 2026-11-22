from core.config.paths import DIR_OUT
from core.export.epub import deduplicate_entries
from core.export.epub.chapters import _collect_printed_toc_titles
from core.export.exporters import export_light_novel, save_ocr_backup
from core.gemini import parse_inline_bold_spans
from core.gemini.markup import strip_structure_tags
from core.ocr import OCRParagraph, is_scene_break_text
from core.vision.image_utils import load_entry_image


class IllustTocReviewMixin:
    def _detect_toc_in_illustrations(self, transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design):
        has_text_toc = bool(_collect_printed_toc_titles(ordered))
        illust_pages = []
        illust_entries_by_page = {}
        for entry in ordered:
            if entry.get("type") != "illustration":
                continue
            page_no = int(entry.get("page_no", 0))
            if page_no <= 0 or (page_no == 1 and entry.get("is_cover", False)):
                continue
            img = original_loader(page_no)
            if img is None:
                img = load_entry_image(entry)
            if img is not None:
                illust_pages.append((page_no, img))
                illust_entries_by_page[page_no] = entry
        if not illust_pages:
            return ordered, chapters
        ill_bs = max(1, int(getattr(self.opts, "gemini_illust_toc_batch_size", 5)))
        total_ill_batches = max(1, (len(illust_pages) + ill_bs - 1) // ill_bs)
        self.progress_stage.emit(f"5/5 삽화 페이지 목차 판별 (0/{total_ill_batches})")
        self.progress.emit(0, total_ill_batches)
        self.log.emit(f"삽화 이미지 목차 후보 판별 시작: {len(illust_pages)}장 ({ill_bs}장씩 묶음)")

        def on_ill_toc_progress(done_b: int, total_b: int):
            self.progress_stage.emit(f"5/5 삽화 페이지 목차 판별 ({done_b}/{total_b})")
            self.progress.emit(done_b, total_b)
            self._emit_token_usage(transcriber)

        try:
            detected = transcriber.detect_toc_from_illustrations(
                illust_pages,
                cancelled_fn=lambda: self._cancelled,
                log_cb=self.log.emit,
                progress_cb=on_ill_toc_progress,
                batch_size=ill_bs,
            )
            self._emit_token_usage(transcriber)
        except InterruptedError:
            raise
        except Exception as exc:
            self.log.emit(f"[삽화 목차 판별 실패] {exc}")
            return ordered, chapters
        if not detected:
            return ordered, chapters
        converted = 0
        chap_candidates = []
        text_entries_sorted = [e for e in sorted(ordered, key=lambda v: int(v.get("page_no", 0))) if e.get("type") == "text"]

        for item in detected:
            page_no = int(item.get("page_no", 0))
            old_ent = illust_entries_by_page.get(page_no)
            if old_ent is None:
                continue
            kind = str(item.get("kind", "")).strip().lower()
            if kind == "chapter_title":
                title = str(item.get("title", "")).strip()
                if title and not has_text_toc:
                    prev_ctx = ""
                    next_ctx = ""
                    for te in text_entries_sorted:
                        tp = int(te.get("page_no", 0))
                        if tp < page_no:
                            snip = self._page_text_snippet(te, from_end=True)
                            if snip:
                                prev_ctx = snip
                        elif tp > page_no and not next_ctx:
                            snip = self._page_text_snippet(te, from_end=False)
                            if snip:
                                next_ctx = snip
                                break
                    chap_candidates.append({
                        "page_no": page_no,
                        "title": title,
                        "prev_context": prev_ctx,
                        "next_context": next_ctx,
                    })
                continue

            toc_title = str(item.get("toc_title", "")).strip() or "目次"
            raw_entries = [str(e).strip() for e in (item.get("entries", []) or []) if str(e).strip()]
            if not raw_entries:
                continue
            paragraphs = [
                OCRParagraph(
                    spans=parse_inline_bold_spans(strip_structure_tags(toc_title), True),
                    block_type="toc_title",
                    reading_order=0,
                )
            ]
            for row_text in raw_entries:
                clean_row = strip_structure_tags(row_text).strip()
                if not clean_row:
                    continue
                paragraphs.append(
                    OCRParagraph(
                        spans=parse_inline_bold_spans(clean_row, False),
                        is_scene_break=is_scene_break_text(clean_row),
                        block_type="toc_entry",
                        reading_order=len(paragraphs),
                        is_toc_entry=True,
                    )
                )
            old_ent["toc_entries"] = raw_entries
            converted += 1
            self.log.emit(f"[삽화 목차 후보 저장] p{page_no}: {len(raw_entries)}개 목차 항목 추출" + (f" ({item['reason']})" if item.get("reason") else ""))

        if chap_candidates:
            existing_ch = [{"order": idx, "title": ch.title} for idx, ch in enumerate(chapters, start=1) if ch.title]
            try:
                approved = transcriber.validate_illustration_chapter_titles(
                    chap_candidates,
                    existing_ch,
                    cancelled_fn=lambda: self._cancelled,
                    log_cb=self.log.emit,
                )
                self._emit_token_usage(transcriber)
            except InterruptedError:
                raise
            except Exception as exc:
                self.log.emit(f"[삽화 목차 문맥 검증 실패] {exc}")
                approved = []
            for app in approved:
                p_no = int(app["page_no"])
                title = app["chapter_title"]
                ent = illust_entries_by_page.get(p_no)
                if ent is not None:
                    ent["chapter_title"] = title
                    converted += 1
                    self.log.emit(f"[삽화 장 분할 적용] p{p_no}: '{title}'" + (f" ({app['reason']})" if app.get("reason") else ""))

        if converted > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
            self.log.emit(f"삽화 목차 반영 완료: {converted}건 적용 · 총 {len(chapters)}개 장으로 EPUB 재생성")
        return ordered, chapters
