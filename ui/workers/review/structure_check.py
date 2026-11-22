import hashlib

from core.config.paths import DIR_OUT
from core.export.epub import deduplicate_entries, is_chapter_heading, read_epub_structure, validate_epub_package
from core.export.epub.chapters import _ordered_paragraphs
from core.export.epub.headings import is_printed_toc_page
from core.export.epub.styles import EpubDesignConfig
from core.export.epub.text_utils import _plain_key
from core.export.exporters import export_light_novel, save_ocr_backup
from core.ocr import TextSpan
from core.vision.image_utils import get_image_size


class StructureCheckWorkerMixin:
    def _run_final_gemini_check(self, transcriber, entries, chapters, epub_path, part_meta_by_page, original_loader, backup_dir):
        ordered = deduplicate_entries(sorted(entries, key=lambda entry: int(entry.get("page_no", 0))))
        design = EpubDesignConfig.from_dict(self.opts.epub_design or {})
        design.writing_mode = self.opts.epub_writing_mode
        design.scene_break_style = self.opts.scene_break_style
        checks = [
            key for enabled, key in (
                (self.opts.gemini_review_ocr, "ocr"),
                (self.opts.gemini_review_paragraphs, "paragraphs"),
                (self.opts.gemini_review_headings, "headings"),
                (self.opts.gemini_review_toc, "toc"),
                (self.opts.gemini_review_duplicates, "duplicates"),
                (self.opts.gemini_review_illustrations, "illustrations"),
            ) if enabled
        ]
        content_checks = [key for key in checks if key != "illustrations"]
        if self.opts.gemini_final_review and content_checks:
            ordered, chapters, cancelled = self._run_content_review_passes(
                transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design, checks, content_checks
            )
            entries[:] = ordered
            if cancelled:
                return
        if not self.opts.gemini_final_review:
            self.log.emit("Gemini 최종 검수가 설정에서 비활성화되어 있습니다.")
            return
        if self.opts.gemini_review_illust_toc and (self.opts.gemini_review_toc or self.opts.gemini_review_headings):
            ordered, chapters = self._detect_toc_in_illustrations(transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design)
            entries[:] = ordered
            if self._cancelled:
                return
            ordered, chapters = self._fix_misclassified_toc_pages(ordered, chapters, epub_path, backup_dir, design)
            entries[:] = ordered
            ordered, chapters = self._reconcile_toc_headings(transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design)
            entries[:] = ordered
            if self._cancelled:
                return
            ordered, chapters = self._fix_misclassified_toc_pages(ordered, chapters, epub_path, backup_dir, design)
            entries[:] = ordered
            ordered, chapters = self._recover_missing_toc_chapters(transcriber, ordered, chapters, epub_path, part_meta_by_page, original_loader, backup_dir, design)
            ordered, chapters = self._cleanup_duplicate_or_inverted_chapters(ordered, chapters, epub_path, backup_dir, design)
            entries[:] = ordered
            if self._cancelled:
                return

        self.progress_stage.emit("5/5 최종 구조·삽화 검수")
        self.progress.emit(0, 3)
        page_summaries = []
        toc_images = []
        illustration_order = 0
        previous_page = 0
        source_page_fingerprints = {}
        duplicate_fingerprints = []
        toc_markers = {"目次", "もくじ", "목차", "차례", "contents", "table of contents"}

        for entry in ordered:
            page_no = int(entry.get("page_no", 0))
            row = {"page": page_no, "type": entry.get("type"), "source": entry.get("source_name", ""), "source_part": entry.get("source_part_index", 0), "fingerprint": entry.get("page_fingerprint", "")[:18]}
            if page_no <= previous_page:
                row["order_warning"] = True
            previous_page = page_no
            fingerprint = entry.get("page_fingerprint", "")
            if fingerprint and entry.get("type") != "illustration":
                if fingerprint in source_page_fingerprints:
                    duplicate_fingerprints.append([page_no, source_page_fingerprints[fingerprint]])
                else:
                    source_page_fingerprints[fingerprint] = page_no
            if entry.get("type") == "illustration":
                illustration_order += 1
                row["illustration_order"] = illustration_order
                row["crop_size"] = list(get_image_size(entry))
                if entry.get("chapter_title"):
                    row["chapter_title"] = entry.get("chapter_title")
                if entry.get("toc_entries") and len(toc_images) < 4 and page_no > 0:
                    loaded = original_loader(page_no)
                    if loaded is not None:
                        toc_images.append((page_no, loaded))
            else:
                paragraphs = entry.get("paragraphs", [])
                row["blocks"] = []
                normalized_ocr = "".join("".join(paragraph.plain_text.split()) for paragraph in paragraphs)
                row["ocr_chars"] = len(normalized_ocr)
                row["ocr_hash"] = hashlib.sha256(normalized_ocr.encode("utf-8")).hexdigest()[:20] if len(normalized_ocr) >= 80 else ""
                for index, paragraph in enumerate(paragraphs):
                    if not paragraph.plain_text.strip():
                        continue
                    row["blocks"].append({
                        "order": paragraph.reading_order if paragraph.reading_order >= 0 else index,
                        "type": "chapter_heading" if is_chapter_heading(paragraph) else paragraph.block_type,
                        "heading_level": paragraph.heading_level if paragraph.is_heading else 0,
                        "toc_entry": paragraph.is_toc_entry,
                        "text": paragraph.plain_text.strip()[:90] if paragraph.is_heading or paragraph.is_toc_entry or paragraph.block_type in {"toc_title", "toc_entry"} else "",
                    })
                if is_printed_toc_page(paragraphs) or any(p.is_toc_entry or p.block_type in {"toc_title", "toc_entry"} or p.plain_text.strip().casefold() in toc_markers for p in paragraphs):
                    if len(toc_images) < 4:
                        loaded = original_loader(page_no)
                        if loaded is not None:
                            toc_images.append((page_no, loaded))
            page_summaries.append(row)

        chapter_summaries = []
        for chapter_index, chapter in enumerate(chapters, start=1):
            items = []
            for item in chapter.items:
                item_type = item.get("type")
                if item_type not in {"heading", "subheading", "toc_entry", "illustration"}:
                    continue
                text = "".join(span.text for span in item.get("spans", [])) if item_type == "toc_entry" else item.get("text", "")
                items.append({"type": item_type, "page": int(item.get("page_no", 0)), "level": int(item.get("level", 0)), "text": str(text)[:90]})
            all_p = [int(it.get("page_no", 0)) for it in chapter.items if int(it.get("page_no", 0)) > 0]
            para_cnt = sum(1 for it in chapter.items if it.get("type") == "paragraph")
            chapter_summaries.append({
                "order": chapter_index,
                "title": chapter.title,
                "in_navigation": bool(chapter.title),
                "page_range": [min(all_p), max(all_p)] if all_p else [],
                "paragraph_count": para_cnt,
                "items": items,
            })

        self.progress.emit(1, 3)
        local_issues = []
        if duplicate_fingerprints:
            local_issues.append("중복 원본 이미지 지문이 남아 있습니다: " + str(duplicate_fingerprints[:12]))
        empty_chapters = [
            ch.title for ch in chapters
            if ch.title and ch.title != "Table of Contents" and sum(1 for it in ch.items if it.get("type") in {"paragraph", "illustration", "toc_entry", "scene_break"}) == 0
        ]
        if empty_chapters:
            local_issues.append(f"본문이 비어 있는 장 {len(empty_chapters)}개 검출 (목차 오분류 의심): " + ", ".join(empty_chapters[:8]))
        try:
            validation = validate_epub_package(epub_path)
            local_issues.extend(validation.get("warnings", []))
            epub_structure = read_epub_structure(epub_path)
            self.log.emit("EPUB 로컬 검사 완료: XML, manifest, spine, 목차 링크, 이미지 참조")
        except Exception as exc:
            epub_structure = {"spine": [], "navigation": []}
            local_issues.append(f"EPUB 로컬 검사 실패: {exc}")

        contact_sheet = self._make_illustration_contact_sheet(ordered, original_loader) if self.opts.gemini_review_illustrations else None
        self.progress.emit(2, 3)
        self.log.emit(f"Gemini 최종 구조 검수: 페이지 {len(page_summaries)}장, 장 {len(chapter_summaries)}개, 인쇄 목차 {len(toc_images)}장, 삽화 {illustration_order}개")
        try:
            audit_res = transcriber.audit_epub_structure(
                page_summaries,
                chapter_summaries,
                epub_structure,
                contact_sheet=contact_sheet,
                toc_images=toc_images,
                cancelled_fn=lambda: self._cancelled,
                log_cb=self.log.emit,
            )
            self._emit_token_usage(transcriber)
            issues = audit_res.get("issues", []) if isinstance(audit_res, dict) else list(audit_res or [])
            fixes = audit_res.get("fixes", {}) if isinstance(audit_res, dict) else {}
            struct_applied = self._apply_structure_fixes(ordered, fixes)
            if struct_applied > 0:
                ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
                entries[:] = ordered
                save_ocr_backup(backup_dir, ordered)
                _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
                self.log.emit(f"최종 구조 검수 수정 반영 완료: {struct_applied}건 · 총 {len(chapters)}개 장으로 EPUB 재생성")
            if issues:
                for issue in issues:
                    self.log.emit(f"[Gemini 최종 구조 검수] {issue}")
            elif struct_applied == 0:
                self.log.emit("Gemini 최종 구조 검수: 명확한 구조·순서·목차·크롭 오류가 발견되지 않았습니다.")
        except Exception as exc:
            self.log.emit(f"[Gemini 최종 구조 검수 실패] {exc}")
        self.progress.emit(3, 3)
        for issue in local_issues:
            self.log.emit(f"[로컬 검사] {issue}")
        self.log.emit("최종 검수 완료: 적용 가능한 본문 수정은 OCR 백업과 EPUB에 반영됨")

    def _apply_structure_fixes(self, ordered, fixes: dict) -> int:
        struct_applied = 0
        by_page_audit = {int(e.get("page_no", 0)): e for e in ordered}
        for dm in fixes.get("demote_headings", []) or []:
            if not isinstance(dm, dict):
                continue
            p_no = int(dm.get("page_no", 0) or 0)
            t_txt = _plain_key(str(dm.get("text", "")))
            to_sec = bool(dm.get("to_section", False))
            ent = by_page_audit.get(p_no)
            if ent and ent.get("type") == "text":
                paras = _ordered_paragraphs(ent.get("paragraphs", []))
                for pr in paras:
                    if pr.is_heading and (not t_txt or _plain_key(pr.plain_text) == t_txt):
                        pr.is_heading = to_sec
                        pr.heading_level = 2 if to_sec else 0
                        pr.block_type = "divider" if to_sec else "paragraph"
                        pr.is_toc_candidate = False
                        pr.is_bic_candidate = to_sec
                        struct_applied += 1
                        self.log.emit(f"[최종 구조 검수 자동 수정] p{p_no}: '{pr.plain_text.strip()[:30]}' → {'구분자' if to_sec else '일반 문단'} ({dm.get('reason', '')})")
                ent["paragraphs"] = paras
        for rn in fixes.get("rename_chapters", []) or []:
            if not isinstance(rn, dict):
                continue
            p_no = int(rn.get("page_no", 0) or 0)
            old_t = _plain_key(str(rn.get("old_title", "")))
            new_t = str(rn.get("new_title", "")).strip()
            ent = by_page_audit.get(p_no)
            if not ent or not new_t:
                continue
            if ent.get("type") == "illustration":
                if not old_t or _plain_key(str(ent.get("chapter_title", ""))) == old_t:
                    ent["chapter_title"] = new_t
                    struct_applied += 1
                    self.log.emit(f"[최종 구조 검수 제목 수정] p{p_no}: '{new_t}' ({rn.get('reason', '')})")
            elif ent.get("type") == "text":
                paras = _ordered_paragraphs(ent.get("paragraphs", []))
                for pr in paras:
                    if pr.is_heading and (not old_t or _plain_key(pr.plain_text) == old_t):
                        pr.spans = [TextSpan(new_t, pr.is_all_bold)]
                        struct_applied += 1
                        self.log.emit(f"[최종 구조 검수 제목 수정] p{p_no}: '{new_t}' ({rn.get('reason', '')})")
                        break
                ent["paragraphs"] = paras
        return struct_applied
