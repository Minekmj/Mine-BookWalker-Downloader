from core.config.paths import DIR_OUT
from core.export.epub import deduplicate_entries, is_chapter_heading, is_section_heading
from core.export.epub.chapters import _collect_printed_toc_titles, _ordered_paragraphs
from core.export.epub.headings import is_printed_toc_page
from core.export.epub.text_utils import _clean_ruby, _plain_key
from core.export.exporters import export_light_novel, save_ocr_backup
from core.ocr import TextSpan


class TocReconcileWorkerMixin:
    def _fix_misclassified_toc_pages(self, ordered, chapters, epub_path, backup_dir, design):
        empty_pages = {}
        for ch in chapters:
            if not ch.title or ch.title == "Table of Contents":
                continue
            body_count = sum(1 for it in ch.items if it.get("type") in {"paragraph", "illustration", "toc_entry", "scene_break"})
            if body_count == 0 and ch.items:
                p_no = int(ch.items[0].get("page_no", 0))
                if p_no > 0:
                    empty_pages[p_no] = empty_pages.get(p_no, 0) + 1
        suspect_pages = {p_no for p_no, cnt in empty_pages.items() if cnt >= 2}
        if not suspect_pages:
            return ordered, chapters
        fixed = 0
        for entry in ordered:
            if entry.get("type") != "text":
                continue
            p_no = int(entry.get("page_no", 0))
            if p_no not in suspect_pages:
                continue
            paras = _ordered_paragraphs(entry.get("paragraphs", []))
            if not paras:
                continue
            has_narrative = any(
                len(_clean_ruby(pr.plain_text).strip()) > 65 or _clean_ruby(pr.plain_text).strip().endswith("。")
                for pr in paras if not pr.is_scene_break
            )
            if has_narrative:
                continue
            for idx_p, pr in enumerate(paras):
                if pr.is_scene_break:
                    continue
                pr.is_heading = False
                pr.heading_level = 0
                if idx_p == 0 and len(_clean_ruby(pr.plain_text).strip()) <= 15 and "目" in pr.plain_text:
                    pr.block_type = "toc_title"
                    pr.is_toc_entry = False
                else:
                    pr.block_type = "toc_entry"
                    pr.is_toc_entry = True
            fixed += 1
            self.log.emit(f"[목차 오분류 자동 보정] p{p_no}: 빈 본문 장을 생성한 제목 나열 페이지를 목차로 변환")
        if fixed > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
        return ordered, chapters

    def _reconcile_toc_headings(self, transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design):
        printed_toc = []
        toc_images = []
        flat_paras = []
        for entry in ordered:
            page_no = int(entry.get("page_no", 0))
            if entry.get("type") == "illustration":
                for row in entry.get("toc_entries", []) or []:
                    t = str(row).strip()
                    if t:
                        printed_toc.append(t)
                if entry.get("toc_entries") and len(toc_images) < 4 and page_no > 0:
                    loaded = original_loader(page_no)
                    if loaded is not None:
                        toc_images.append((page_no, loaded))
                continue
            if entry.get("type") != "text":
                continue
            paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
            if is_printed_toc_page(paragraphs):
                if len(toc_images) < 4 and page_no > 0:
                    loaded = original_loader(page_no)
                    if loaded is not None:
                        toc_images.append((page_no, loaded))
                for p in paragraphs:
                    t = _clean_ruby(p.plain_text).strip()
                    if t and p.block_type != "toc_title":
                        printed_toc.append(t)
                for idx, p in enumerate(paragraphs):
                    flat_paras.append((page_no, idx, p, True))
                continue
            for idx, p in enumerate(paragraphs):
                flat_paras.append((page_no, idx, p, False))

        candidates = []
        title_count = 0
        bic_count = 0
        for flat_idx, (page_no, idx, p, is_toc) in enumerate(flat_paras):
            if is_toc or p.is_scene_break or p.is_toc_entry:
                continue
            t = _clean_ruby(p.plain_text).strip()
            if not t:
                continue
            if p.is_toc_candidate or p.is_bic_candidate:
                tag_type = "title" if p.is_toc_candidate else "bic"
                if tag_type == "title":
                    title_count += 1
                else:
                    bic_count += 1
                candidates.append({
                    "page_no": page_no,
                    "para_index": idx,
                    "text": t[:90],
                    "tag_type": tag_type,
                    "from_title": tag_type == "title",
                    "from_bic": tag_type == "bic",
                    "is_chapter_now": is_chapter_heading(p),
                    "is_section_now": is_section_heading(p),
                    "prev_context": self._collect_context_window(flat_paras, flat_idx, -1),
                    "next_context": self._collect_context_window(flat_paras, flat_idx, 1),
                })
                continue
            if len(t) > 65 or t.startswith(("「", "『", "（", "(")) or t.endswith(("。", "、", "」", "』")):
                continue
            if idx < 6 or p.is_heading or p.is_all_bold or len(t) <= 35 or any(sym in t for sym in "◆◇■□●○★☆第章話節"):
                candidates.append({
                    "page_no": page_no,
                    "para_index": idx,
                    "text": t,
                    "tag_type": "none",
                    "from_title": False,
                    "from_bic": False,
                    "is_chapter_now": is_chapter_heading(p),
                    "is_section_now": is_section_heading(p),
                    "prev_context": self._collect_context_window(flat_paras, flat_idx, -1),
                    "next_context": self._collect_context_window(flat_paras, flat_idx, 1),
                })

        if not candidates:
            return ordered, chapters
        if not printed_toc and not toc_images and title_count == 0 and bic_count == 0:
            return ordered, chapters

        current_chapters = [{"order": idx, "title": ch.title} for idx, ch in enumerate(chapters, start=1) if ch.title]
        self.progress_stage.emit("5/5 <title>·<bic> 문맥 판별 및 상호 교정")
        self.progress.emit(0, 2)
        self.log.emit(f"Gemini 목차·구분자 문맥 검수: <title> {title_count}개 · <bic> {bic_count}개 · 전체 후보 {len(candidates)}개 · 인쇄 목차 {len(printed_toc)}개")
        try:
            res = transcriber.reconcile_chapters_and_toc(
                printed_toc,
                current_chapters,
                candidates,
                toc_images=toc_images,
                cancelled_fn=lambda: self._cancelled,
                log_cb=self.log.emit,
            )
            self._emit_token_usage(transcriber)
        except Exception as exc:
            self.log.emit(f"[목차·구분자 재구성 검수 실패] {exc}")
            self.progress.emit(2, 2)
            return ordered, chapters
        self.progress.emit(1, 2)

        promotions = res.get("promotions", []) if isinstance(res, dict) else []
        demotions = res.get("demotions", []) if isinstance(res, dict) else []
        if not promotions and not demotions:
            self.progress.emit(2, 2)
            return ordered, chapters

        by_page = {int(entry.get("page_no", 0)): entry for entry in ordered if entry.get("type") == "text"}
        applied = 0
        for item in promotions:
            page_no = item["page_no"]
            para_index = item["para_index"]
            title = item["chapter_title"]
            level = max(1, min(2, int(item.get("heading_level", 1) or 1)))
            entry = by_page.get(page_no)
            if not entry:
                continue
            paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
            if not (0 <= para_index < len(paragraphs)):
                continue
            target_p = paragraphs[para_index]
            was_title = target_p.is_toc_candidate
            was_bic = target_p.is_bic_candidate
            target_p.is_toc_entry = False
            target_p.is_scene_break = False
            target_p.is_heading = True
            target_p.heading_level = level
            target_p.block_type = "chapter_heading" if level == 1 else "divider"
            target_p.is_toc_candidate = level == 1
            target_p.is_bic_candidate = level == 2
            entry["paragraphs"] = paragraphs
            cur_plain = _clean_ruby(target_p.plain_text).strip()
            if level == 1 and title and cur_plain != title and len(title) >= len(cur_plain):
                target_p.spans = [TextSpan(title, target_p.is_all_bold)]
            applied += 1
            if level == 1 and was_bic:
                kind = "구분자→목차 교정"
            elif level == 2 and was_title:
                kind = "목차→구분자 교정"
            else:
                kind = "장 제목(title)" if level == 1 else "구분자(bic)"
            self.log.emit(f"[목차·구분자 반영 · {kind}] p{page_no}: '{title}'" + (f" ({item['reason']})" if item.get("reason") else ""))

        for item in demotions:
            page_no = item["page_no"]
            para_index = item["para_index"]
            entry = by_page.get(page_no)
            if not entry:
                continue
            paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
            if not (0 <= para_index < len(paragraphs)):
                continue
            target_p = paragraphs[para_index]
            if target_p.is_heading or target_p.is_toc_candidate or target_p.is_bic_candidate:
                target_p.is_heading = False
                target_p.heading_level = 0
                target_p.block_type = "paragraph"
                target_p.is_toc_candidate = False
                target_p.is_bic_candidate = False
                applied += 1
                self.log.emit(f"[제목·구분자 제외 반영] p{page_no}: '{_clean_ruby(target_p.plain_text).strip()[:30]}'")

        if applied > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
            self.log.emit(f"목차·구분자 재구성 완료: {applied}건 반영 · 총 {len(chapters)}개 장으로 EPUB 재생성")
        self.progress.emit(2, 2)
        return ordered, chapters

    def _cleanup_duplicate_or_inverted_chapters(self, ordered, chapters, epub_path, backup_dir, design):
        toc_titles = _collect_printed_toc_titles(ordered)
        toc_order = {_plain_key(t): idx for idx, (t, _, _) in enumerate(toc_titles)}
        seen = {}
        drop_pages = set()
        for ch in chapters:
            if not ch.title or ch.title == "Table of Contents":
                continue
            k = _plain_key(ch.title)
            pages = [int(it.get("page_no", 0)) for it in ch.items if int(it.get("page_no", 0)) > 0]
            if not pages:
                continue
            p_no = min(pages)
            body_cnt = sum(1 for it in ch.items if it.get("type") in {"paragraph", "illustration", "scene_break"})
            if k in seen:
                prev_p, prev_body, prev_title = seen[k]
                prev_idx = toc_order.get(k, -1)
                later_conflict = False
                if prev_idx >= 0:
                    for ch2 in chapters:
                        if not ch2.title:
                            continue
                        k2 = _plain_key(ch2.title)
                        idx2 = toc_order.get(k2, -1)
                        p2s = [int(it.get("page_no", 0)) for it in ch2.items if int(it.get("page_no", 0)) > 0]
                        if idx2 >= 0 and p2s:
                            p2 = min(p2s)
                            if idx2 < prev_idx and prev_p < p2 < p_no:
                                later_conflict = True
                                break
                if later_conflict or (prev_body == 0 and body_cnt > 0):
                    drop_pages.add((prev_p, k))
                    seen[k] = (p_no, body_cnt, ch.title)
                else:
                    drop_pages.add((p_no, k))
            else:
                seen[k] = (p_no, body_cnt, ch.title)
        if not drop_pages:
            return ordered, chapters
        fixed = 0
        for entry in ordered:
            p_no = int(entry.get("page_no", 0))
            if entry.get("type") == "illustration":
                ct = str(entry.get("chapter_title", "")).strip()
                if ct and (p_no, _plain_key(ct)) in drop_pages:
                    entry.pop("chapter_title", None)
                    fixed += 1
                    self.log.emit(f"[중복 목차 자동 정리] p{p_no}: '{ct}'")
            elif entry.get("type") == "text":
                paras = _ordered_paragraphs(entry.get("paragraphs", []))
                for pr in paras:
                    if pr.is_heading and (p_no, _plain_key(pr.plain_text)) in drop_pages:
                        pr.is_heading = False
                        pr.heading_level = 0
                        pr.block_type = "paragraph"
                        pr.is_toc_candidate = False
                        fixed += 1
                        self.log.emit(f"[중복 목차 자동 정리] p{p_no}: '{pr.plain_text.strip()[:30]}'")
                entry["paragraphs"] = paras
        if fixed > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
        return ordered, chapters
