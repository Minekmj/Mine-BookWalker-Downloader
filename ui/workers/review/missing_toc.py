from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from core.config.paths import DIR_OUT
from core.export.epub import deduplicate_entries
from core.export.epub.chapters import _collect_printed_toc_titles, _ordered_paragraphs
from core.export.epub.headings import is_printed_toc_page
from core.export.epub.text_utils import _clean_ruby, _plain_key
from core.export.exporters import export_light_novel, save_ocr_backup
from core.gemini import parse_inline_bold_spans
from core.gemini.markup import strip_structure_tags
from core.ocr import OCRParagraph, TextSpan, is_scene_break_text


class MissingTocWorkerMixin:
    @staticmethod
    def _is_missing_toc_candidate_page(by_page, p_no: int, prev_was_non_text: bool) -> bool:
        ent = by_page.get(p_no)
        if ent is None:
            return True
        if ent.get("type") == "illustration":
            return not (p_no == 1 and ent.get("is_cover", False))
        paras = _ordered_paragraphs(ent.get("paragraphs", []))
        if not paras:
            return True
        if is_printed_toc_page(paras):
            return False
        if prev_was_non_text:
            return True
        total_chars = sum(len(_clean_ruby(pr.plain_text).strip()) for pr in paras)
        if len(paras) <= 6 or total_chars <= 320:
            return True
        for pr in paras[:3]:
            t = _clean_ruby(pr.plain_text).strip()
            if not t:
                continue
            if pr.is_heading or pr.is_toc_candidate or pr.is_all_bold:
                return True
            if len(t) <= 45 and not t.startswith(("「", "『", "（", "(")) and not t.endswith(("。", "、", "」", "』")):
                return True
        return False

    def _apply_recovered_chapter(self, item, ordered, by_page, part_meta_by_page, remaining_titles):
        p_no = item["page_no"]
        title = item["chapter_title"]
        para_idx = item["para_index"]
        need_reocr = item["need_full_reocr"]
        raw_paras = item["paragraphs"]
        if title in remaining_titles:
            remaining_titles.remove(title)

        ent = by_page.get(p_no)
        if ent is not None and ent.get("type") == "illustration":
            ent["chapter_title"] = title
            self.log.emit(f"[누락 목차 이미지 장 분할] p{p_no}: '{title}'" + (f" ({item['reason']})" if item.get("reason") else ""))
            return ordered, True

        if (ent is None or need_reocr) and raw_paras:
            new_paras = []
            has_title_in_paras = False
            t_key = _plain_key(title)
            for r_idx, r_txt in enumerate(raw_paras):
                clean_r = strip_structure_tags(r_txt).strip()
                if not clean_r:
                    continue
                is_t = (_plain_key(clean_r) == t_key) or (r_idx == 0 and len(clean_r) <= 65 and _plain_key(clean_r) in t_key)
                if is_t and not has_title_in_paras:
                    new_paras.append(OCRParagraph(spans=[TextSpan(title, True)], is_heading=True, heading_level=1, block_type="chapter_heading", reading_order=len(new_paras)))
                    has_title_in_paras = True
                else:
                    new_paras.append(
                        OCRParagraph(
                            spans=parse_inline_bold_spans(clean_r, False),
                            is_scene_break=is_scene_break_text(clean_r),
                            reading_order=len(new_paras),
                        )
                    )
            if not has_title_in_paras:
                new_paras.insert(0, OCRParagraph(spans=[TextSpan(title, True)], is_heading=True, heading_level=1, block_type="chapter_heading", reading_order=0))
                for idx_u, p_u in enumerate(new_paras):
                    p_u.reading_order = idx_u
            src_name, p_idx_m, part_m, fp_m = part_meta_by_page.get(p_no, ("", 0, None, ""))
            if ent is not None and ent.get("type") == "text":
                ent["paragraphs"] = new_paras
                ent["ocr_error"] = ""
            elif part_m is not None:
                new_ent = {
                    "type": "text",
                    "page_no": p_no,
                    "source_name": src_name,
                    "source_part_index": p_idx_m,
                    "source_key": ent.get("source_key", "") if ent else "",
                    "page_fingerprint": fp_m,
                    "paragraphs": new_paras,
                    "ocr_error": "",
                }
                if ent is not None:
                    ordered = [new_ent if int(e.get("page_no", 0)) == p_no else e for e in ordered]
                else:
                    ordered.append(new_ent)
                by_page[p_no] = new_ent
        elif ent is not None and ent.get("type") == "text":
            paras = _ordered_paragraphs(ent.get("paragraphs", []))
            if 0 <= para_idx < len(paras):
                tp = paras[para_idx]
                tp.is_toc_entry = False
                tp.is_scene_break = False
                tp.is_heading = True
                tp.heading_level = 1
                tp.block_type = "chapter_heading"
                tp.spans = [TextSpan(title, tp.is_all_bold)]
                ent["paragraphs"] = paras
            else:
                paras.insert(
                    0,
                    OCRParagraph(
                        spans=[TextSpan(title, True)],
                        is_heading=True,
                        heading_level=1,
                        block_type="chapter_heading",
                        reading_order=0,
                    ),
                )
                for idx_u, p_u in enumerate(paras):
                    p_u.reading_order = idx_u
                ent["paragraphs"] = paras

        self.log.emit(f"[누락 목차 이미지 복구] p{p_no}: '{title}'" + (f" ({item['reason']})" if item.get("reason") else ""))
        return ordered, True

    def _recover_missing_toc_chapters(self, transcriber, ordered, chapters, epub_path, part_meta_by_page, original_loader, backup_dir, design):
        toc_titles = _collect_printed_toc_titles(ordered)
        if not toc_titles:
            return ordered, chapters

        ch_list = []
        for ch in chapters:
            if not ch.title or ch.title == "Table of Contents":
                continue
            pages_in_ch = [int(it.get("page_no", 0)) for it in ch.items if int(it.get("page_no", 0)) > 0]
            first_p = min(pages_in_ch) if pages_in_ch else 0
            ch_list.append((ch.title, _plain_key(ch.title), first_p))

        anchor_page_by_toc_idx = {}
        used_ch = set()
        for t_idx, (_, t_full_key, t_suffix_key) in enumerate(toc_titles):
            for c_idx, (_, c_key, c_page) in enumerate(ch_list):
                if c_idx in used_ch or c_page <= 0:
                    continue
                if c_key == t_full_key or (t_suffix_key and len(t_suffix_key) >= 3 and (c_key == t_suffix_key or c_key.endswith(t_suffix_key) or t_full_key in c_key)):
                    anchor_page_by_toc_idx[t_idx] = c_page
                    used_ch.add(c_idx)
                    break

        missing_indices = [idx for idx in range(len(toc_titles)) if idx not in anchor_page_by_toc_idx]
        if not missing_indices:
            return ordered, chapters

        max_page_no = max([int(e.get("page_no", 0)) for e in ordered] + list(part_meta_by_page.keys()), default=1)
        intervals = []
        cur_group = []
        cur_range = None
        for m_idx in missing_indices:
            prev_p = next((anchor_page_by_toc_idx[j] for j in range(m_idx - 1, -1, -1) if j in anchor_page_by_toc_idx), 1)
            next_p = next((anchor_page_by_toc_idx[j] for j in range(m_idx + 1, len(toc_titles)) if j in anchor_page_by_toc_idx), max_page_no)
            rng = (max(1, prev_p), min(max_page_no, next_p))
            if cur_range == rng:
                cur_group.append(toc_titles[m_idx][0])
            else:
                if cur_group and cur_range is not None:
                    intervals.append((cur_group, cur_range[0], cur_range[1]))
                cur_group = [toc_titles[m_idx][0]]
                cur_range = rng
        if cur_group and cur_range is not None:
            intervals.append((cur_group, cur_range[0], cur_range[1]))
        if not intervals:
            return ordered, chapters

        by_page = {int(entry.get("page_no", 0)): entry for entry in ordered}
        interval_batches = []
        total_img_batches = 0
        for m_titles, start_p, end_p in intervals:
            all_range = [p for p in range(start_p, end_p + 1) if p in part_meta_by_page]
            cand_pages = []
            prev_non_text = True
            for p_no in all_range:
                ent = by_page.get(p_no)
                if self._is_missing_toc_candidate_page(by_page, p_no, prev_non_text):
                    cand_pages.append(p_no)
                prev_non_text = (ent is None or ent.get("type") == "illustration")
            target_pages = cand_pages if cand_pages else all_range
            miss_bs = max(1, int(getattr(self.opts, "gemini_missing_toc_batch_size", 8)))
            img_batches = [target_pages[i:i + miss_bs] for i in range(0, len(target_pages), miss_bs)]
            interval_batches.append((m_titles, start_p, end_p, target_pages, img_batches))
            total_img_batches += max(1, len(img_batches))

        self.progress_stage.emit(f"5/5 누락 목차 구간 이미지 탐색 (0/{total_img_batches})")
        self.progress.emit(0, total_img_batches)
        self.log.emit(f"누락된 인쇄 목차 {len(missing_indices)}개 감지 → {len(intervals)}개 구간 (후보 {sum(len(x[3]) for x in interval_batches)}장 / {total_img_batches}개 묶음) 병렬 복구 시작")

        recovered_total = 0
        done_img_batches = 0
        max_workers = max(1, min(4, int(self.opts.gemini_max_concurrent)))

        for m_titles, start_p, end_p, target_pages, img_batches in interval_batches:
            if self._cancelled:
                break
            range_meta = []
            for p_no in target_pages:
                ent = by_page.get(p_no)
                if ent is None:
                    range_meta.append({"page_no": p_no, "type": "missing_or_blank", "preview": ""})
                elif ent.get("type") == "illustration":
                    range_meta.append({"page_no": p_no, "type": "illustration", "reason": ent.get("reason", ""), "preview": ""})
                else:
                    paras = _ordered_paragraphs(ent.get("paragraphs", []))
                    if is_printed_toc_page(paras):
                        continue
                    range_meta.append({"page_no": p_no, "type": "text", "para_count": len(paras), "first_lines": [_clean_ruby(p.plain_text).strip()[:60] for p in paras[:4]]})

            remaining_titles = list(m_titles)
            if not img_batches:
                done_img_batches += 1
                self.progress_stage.emit(f"5/5 누락 목차 구간 이미지 탐색 ({done_img_batches}/{total_img_batches})")
                self.progress.emit(done_img_batches, total_img_batches)
                continue

            def run_one_batch(b_pages):
                b_meta = [m for m in range_meta if m["page_no"] in set(b_pages)]
                b_imgs = [(p, img) for p in b_pages if (img := original_loader(p)) is not None]
                return transcriber.locate_missing_chapters_in_range(
                    list(remaining_titles), b_meta, range_images=b_imgs, cancelled_fn=lambda: self._cancelled, log_cb=self.log.emit
                )

            batch_results = []
            ex = ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(img_batches))))
            try:
                futs = {ex.submit(run_one_batch, bp): bp for bp in img_batches}
                pending = set(futs.keys())
                while pending:
                    if self._cancelled:
                        ex.shutdown(wait=False, cancel_futures=True)
                        return ordered, chapters
                    done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                    for fut in done:
                        done_img_batches += 1
                        self.progress_stage.emit(f"5/5 누락 목차 구간 이미지 탐색 ({done_img_batches}/{total_img_batches})")
                        self.progress.emit(done_img_batches, total_img_batches)
                        try:
                            found = fut.result()
                            self._emit_token_usage(transcriber)
                            if found:
                                batch_results.extend(found)
                        except InterruptedError:
                            ex.shutdown(wait=False, cancel_futures=True)
                            return ordered, chapters
                        except Exception as exc:
                            self.log.emit(f"[누락 목차 구간 {start_p}~{end_p} 탐색 실패] {exc}")
            except BaseException:
                ex.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                ex.shutdown(wait=True)

            existing_ch_keys = {_plain_key(c_t) for c_t, _, _ in ch_list}
            toc_pos_map = {_plain_key(t_t): idx_t for idx_t, (t_t, _, _) in enumerate(toc_titles)}
            deduped_found = []
            seen_found_keys = set()
            last_accepted_p = start_p - 1
            for item in sorted(batch_results, key=lambda x: (toc_pos_map.get(_plain_key(str(x.get("chapter_title", ""))), 999999), int(x.get("page_no", 0)))):
                t_key = _plain_key(str(item.get("chapter_title", "")))
                p_no_item = int(item.get("page_no", 0))
                if not t_key or t_key in seen_found_keys or t_key in existing_ch_keys:
                    continue
                if p_no_item < start_p or p_no_item > end_p or p_no_item <= last_accepted_p:
                    continue
                seen_found_keys.add(t_key)
                existing_ch_keys.add(t_key)
                last_accepted_p = p_no_item
                deduped_found.append(item)
            for item in deduped_found:
                ordered, ok = self._apply_recovered_chapter(item, ordered, by_page, part_meta_by_page, remaining_titles)
                if ok:
                    recovered_total += 1

        if recovered_total > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
            self.log.emit(f"누락 목차 복구 완료: {recovered_total}개 장 추가 · 총 {len(chapters)}개 장으로 EPUB 재생성")
        return ordered, chapters
