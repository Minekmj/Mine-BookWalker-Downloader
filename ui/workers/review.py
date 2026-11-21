from difflib import SequenceMatcher
import hashlib
import re
from PIL import Image, ImageDraw, ImageFont
from core.epub import deduplicate_entries, is_chapter_heading, is_section_heading, read_epub_structure, validate_epub_package
from core.epub.chapters import _collect_printed_toc_titles, _ordered_paragraphs
from core.epub.headings import is_printed_toc_page
from core.epub.styles import EpubDesignConfig
from core.epub.text_utils import _clean_ruby, _plain_key
from core.exporters import export_light_novel, save_ocr_backup
from core.gemini import compute_page_zscores, parse_inline_bold_spans, summarize_page_for_zscore
from core.gemini.markup import _has_repetition_loop, strip_ft_tags
from core.ocr_engine import OCRParagraph, TextSpan, is_scene_break_text
from core.image_utils import get_image_size, load_entry_image
from core.paths import DIR_OUT

_STRIP_TAG_SPACE_RE = re.compile(r"</?(?:b|ft)\b[^>]*>", re.IGNORECASE)
_SPACE_RE = re.compile(r"[\s\u3000]+")


def _strip_for_diff(text: str) -> str:
    cleaned = _STRIP_TAG_SPACE_RE.sub("", text or "")
    return _SPACE_RE.sub("", cleaned)


def _is_safe_content_correction(old_text: str, new_text: str) -> bool:
    old_plain = _strip_for_diff(old_text)
    new_plain = _strip_for_diff(new_text)
    if not old_plain:
        return False
    if old_plain == new_plain:
        return True
    matcher = SequenceMatcher(None, old_plain, new_plain)
    if matcher.ratio() < 0.90:
        return False
    max_ins = 0
    max_del = 0
    total_change = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        d_len = i2 - i1
        i_len = j2 - j1
        if d_len > max_del:
            max_del = d_len
        if i_len > max_ins:
            max_ins = i_len
        total_change += max(d_len, i_len)
    if max_ins > 5 or max_del > 5:
        return False
    if total_change > max(8, int(len(old_plain) * 0.06)):
        return False
    return True


class ReviewMixin():
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
        z_records, stats = compute_page_zscores(z_records, self.opts.gemini_z_threshold)
        anomalies = [record for record in z_records if record["z_anomaly"] or record["page_no"] in failed_pages]
        if not anomalies:
            return
        self.log.emit(f"OCR 통계 검토: {len(anomalies)}페이지 확인 필요")
        total_anom = len(anomalies)
        self.progress_stage.emit(f"3/5 이상치 검토 (0/{total_anom})")
        self.progress.emit(0, total_anom)
        policy = self.opts.gemini_on_fail_action
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
                result_map, retry_failures = transcriber.transcribe_batch_resilient([(page_no, target_img)], cancelled_fn=lambda: self._cancelled, log_cb=self.log.emit, start_temp=retry_start_temp, max_attempts=1)
                self._emit_token_usage(transcriber)
                retry_result = result_map.get(page_no)
                if retry_result and retry_result.paragraphs:
                    retry_text = self._paragraphs_to_editable_text(retry_result.paragraphs)
            decision = {"action": policy}
            if policy == "ask":
                decision = self._ask_user_review({
                    "page_no": page_no,
                    "source_name": source_name,
                    "image": target_img,
                    "reason": error,
                    "actual_chars": record.get("char_count", 0),
                    "expected_chars": record.get("expected_chars", 0),
                    "z_score": record.get("z_score", 0),
                    "current_text": current_text,
                    "current_model": self.opts.gemini_model,
                    "current_temp": cur_page_temp,
                    "retry_candidate_text": retry_text,
                })
            action = decision.get("action", "keep_edited")
            if action == "cancel":
                self._cancelled = True
                return
            if action == "retry_gemini":
                retry_temp = float(decision.get("temperature", cur_page_temp))
                result_map, retry_failures = transcriber.transcribe_batch_resilient([(page_no, target_img)], cancelled_fn=lambda: self._cancelled, log_cb=self.log.emit, start_temp=retry_temp, model_override=decision.get("model") or self.opts.gemini_model, max_attempts=1)
                self._emit_token_usage(transcriber)
                result = result_map.get(page_no)
                if result and result.paragraphs:
                    entries_map[page_no] = self._make_text_entry(page_no, source_name, part_index, part, source_key, result.paragraphs, fingerprint=fp)
                    self.log.emit(f"[OCR 재시도 반영] p{page_no}")
                else:
                    self.log.emit(f"[OCR 재시도 실패] p{page_no}: {retry_failures.get(page_no, '결과 없음')}")
            elif action == "illustration":
                self.log.emit(f"[사용자 분류] p{page_no}: 삽화로 저장")
                entries_map[page_no] = self._make_illustration_entry(
                    page_no,
                    source_name,
                    part_index,
                    part,
                    source_key,
                    "사용자 미리보기/검수 지정 삽화",
                    raw_image=target_img,
                    fingerprint=fp,
                )
            elif action == "skip":
                entries_map.pop(page_no, None)
            elif decision.get("edited_text") is not None:
                paragraphs = self._editable_text_to_paragraphs(decision["edited_text"])
                entries_map[page_no] = self._make_text_entry(page_no, source_name, part_index, part, source_key, paragraphs, fingerprint=fp)
            else:
                self.log.emit(f"[기존 OCR 유지] p{page_no}")
            self.progress_stage.emit(f"3/5 이상치 검토 ({idx}/{total_anom})")
            self.progress.emit(idx, total_anom)

    def _make_illustration_contact_sheet(self, entries, original_loader):
        illustrations = [entry for entry in sorted(entries, key=lambda value: int(value.get("page_no", 0))) if entry.get("type") == "illustration" and (entry.get("image") is not None or entry.get("image_path"))]
        if not illustrations:
            return None
        thumb_width, thumb_height = 72, 92
        pair_gap, cell_gap, label_height = 8, 8, 18
        columns = min(20, max(4, int((len(illustrations) * 1.5) ** 0.5 + 0.5)))
        cell_width = thumb_width * 2 + pair_gap
        cell_height = thumb_height + label_height + 8
        rows = (len(illustrations) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_width + (columns + 1) * cell_gap, rows * cell_height + (rows + 1) * cell_gap), "white")
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.load_default(size=12)
        except TypeError:
            font = ImageFont.load_default()
        for index, entry in enumerate(illustrations):
            column, row = index % columns, index // columns
            x = cell_gap + column * (cell_width + cell_gap)
            y = cell_gap + row * (cell_height + cell_gap)
            page_no = int(entry["page_no"])
            draw.text((x, y), f"ILLUST {index + 1} / PAGE {page_no}", fill="black", font=font)
            orig_img = original_loader(page_no)
            cropped_img = load_entry_image(entry)
            for offset, label, image in ((0, "ORIGINAL", orig_img), (thumb_width + pair_gap, "CROPPED", cropped_img)):
                draw.text((x + offset, y + label_height), label, fill=(50, 50, 50), font=font)
                if image is None:
                    continue
                thumb = image.convert("RGB")
                thumb.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
                px = x + offset + (thumb_width - thumb.width) // 2
                py = y + label_height + 6 + (thumb_height - thumb.height) // 2
                sheet.paste(thumb, (px, py))
                draw.rectangle((x + offset, y + label_height + 6, x + offset + thumb_width - 1, y + label_height + thumb_height + 5), outline=(130, 130, 130))
        return sheet

    def _collect_context_window(self, flat_paras, center_pos: int, direction: int, limit_chars: int = 180) -> str:
        collected = []
        total_len = 0
        pos = center_pos + direction
        steps = 0
        while 0 <= pos < len(flat_paras) and steps < 4 and total_len < limit_chars:
            _, _, p, is_toc = flat_paras[pos]
            if not is_toc and not p.is_scene_break and not p.is_toc_entry:
                t = _clean_ruby(p.plain_text).strip()
                if t:
                    collected.append(t[:100])
                    total_len += len(t)
                    steps += 1
            pos += direction
        if direction < 0:
            collected.reverse()
        return " / ".join(collected)

    def _reconcile_toc_headings(self, transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design):
        printed_toc = []
        toc_images = []
        flat_paras = []
        toc_markers = {"目次", "もくじ", "목차", "차례", "contents", "table of contents"}

        for entry in ordered:
            if entry.get("type") != "text":
                continue
            page_no = int(entry.get("page_no", 0))
            paragraphs = _ordered_paragraphs(entry.get("paragraphs", []))
            if not paragraphs:
                continue
            is_toc = is_printed_toc_page(paragraphs)
            if is_toc or any(p.is_toc_entry or p.block_type in {"toc_title", "toc_entry"} or p.plain_text.strip().casefold() in toc_markers for p in paragraphs):
                if len(toc_images) < 4:
                    img = original_loader(page_no)
                    if img is not None:
                        toc_images.append((page_no, img))
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
        ft_count = 0
        for flat_idx, (page_no, idx, p, is_toc) in enumerate(flat_paras):
            if is_toc or p.is_scene_break or p.is_toc_entry:
                continue
            t = _clean_ruby(p.plain_text).strip()
            if not t:
                continue
            if p.is_toc_candidate:
                ft_count += 1
                candidates.append({
                    "page_no": page_no,
                    "para_index": idx,
                    "text": t[:90],
                    "from_ft": True,
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
                    "from_ft": False,
                    "is_chapter_now": is_chapter_heading(p),
                    "is_section_now": is_section_heading(p),
                    "prev_context": self._collect_context_window(flat_paras, flat_idx, -1),
                    "next_context": self._collect_context_window(flat_paras, flat_idx, 1),
                })

        if not candidates:
            return ordered, chapters
        if not printed_toc and not toc_images and ft_count == 0:
            return ordered, chapters

        current_chapters = [{"order": idx, "title": ch.title} for idx, ch in enumerate(chapters, start=1) if ch.title]
        self.progress_stage.emit("5/5 <ft>·목차 문맥 판별 및 재구성")
        self.progress.emit(0, 2)
        self.log.emit(f"Gemini 목차 후보 문맥 검수: <ft> 후보 {ft_count}개 · 전체 후보 {len(candidates)}개 · 인쇄 목차 {len(printed_toc)}개")
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
            self.log.emit(f"[목차 재구성 검수 실패] {exc}")
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
            target_p.is_heading = True
            target_p.heading_level = level
            target_p.block_type = "chapter_heading" if level == 1 else "section_heading"
            cur_plain = _clean_ruby(target_p.plain_text).strip()
            if title and cur_plain != title and len(title) >= len(cur_plain):
                target_p.spans = [TextSpan(title, target_p.is_all_bold)]
            applied += 1
            kind = "장 제목" if level == 1 else "소제목"
            self.log.emit(f"[목차 복구 반영 · {kind}] p{page_no}: '{title}'" + (f" ({item['reason']})" if item.get("reason") else ""))

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
            if target_p.is_heading:
                target_p.is_heading = False
                target_p.heading_level = 0
                target_p.block_type = "paragraph"
                applied += 1
                self.log.emit(f"[제목 제외 반영] p{page_no}: '{_clean_ruby(target_p.plain_text).strip()[:30]}'")

        if applied > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
            self.log.emit(f"목차 재구성 완료: {applied}건 반영 · 총 {len(chapters)}개 장으로 EPUB 재생성")
        self.progress.emit(2, 2)
        return ordered, chapters

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
            ch_key = _plain_key(ch.title)
            ch_list.append((ch.title, ch_key, first_p))

        anchor_page_by_toc_idx = {}
        used_ch = set()
        for t_idx, (t_title, t_full_key, t_suffix_key) in enumerate(toc_titles):
            for c_idx, (c_title, c_key, c_page) in enumerate(ch_list):
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
            prev_p = 1
            for j in range(m_idx - 1, -1, -1):
                if j in anchor_page_by_toc_idx:
                    prev_p = anchor_page_by_toc_idx[j]
                    break
            next_p = max_page_no
            for j in range(m_idx + 1, len(toc_titles)):
                if j in anchor_page_by_toc_idx:
                    next_p = anchor_page_by_toc_idx[j]
                    break
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

        self.progress_stage.emit(f"5/5 누락 목차 구간 이미지 탐색 (0/{len(intervals)})")
        self.progress.emit(0, len(intervals))
        self.log.emit(f"누락된 인쇄 목차 {len(missing_indices)}개 감지 → {len(intervals)}개 구간 이미지 정밀 복구 시작")

        by_page = {int(entry.get("page_no", 0)): entry for entry in ordered}
        recovered_total = 0

        for iv_idx, (m_titles, start_p, end_p) in enumerate(intervals, start=1):
            if self._cancelled:
                break
            pages_in_range = [p for p in range(start_p, end_p + 1) if p in part_meta_by_page]
            range_meta = []
            for p_no in range(start_p, end_p + 1):
                ent = by_page.get(p_no)
                if ent is None:
                    range_meta.append({"page_no": p_no, "type": "missing_or_blank", "preview": ""})
                elif ent.get("type") == "illustration":
                    range_meta.append({"page_no": p_no, "type": "illustration", "reason": ent.get("reason", ""), "preview": ""})
                else:
                    paras = _ordered_paragraphs(ent.get("paragraphs", []))
                    if is_printed_toc_page(paras):
                        continue
                    snippets = [_clean_ruby(p.plain_text).strip()[:60] for p in paras[:4]]
                    range_meta.append({"page_no": p_no, "type": "text", "para_count": len(paras), "first_lines": snippets})

            remaining_titles = list(m_titles)
            img_batches = [pages_in_range[i:i + 8] for i in range(0, len(pages_in_range), 8)]
            for b_pages in img_batches:
                if not remaining_titles or self._cancelled:
                    break
                b_meta = [m for m in range_meta if m["page_no"] in set(b_pages)]
                b_imgs = []
                for p in b_pages:
                    loaded = original_loader(p)
                    if loaded is not None:
                        b_imgs.append((p, loaded))
                try:
                    found_items = transcriber.locate_missing_chapters_in_range(
                        remaining_titles,
                        b_meta,
                        range_images=b_imgs,
                        cancelled_fn=lambda: self._cancelled,
                        log_cb=self.log.emit,
                    )
                    self._emit_token_usage(transcriber)
                except InterruptedError:
                    return ordered, chapters
                except Exception as exc:
                    self.log.emit(f"[누락 목차 구간 {start_p}~{end_p} 탐색 실패] {exc}")
                    continue

                for item in found_items:
                    p_no = item["page_no"]
                    title = item["chapter_title"]
                    para_idx = item["para_index"]
                    need_reocr = item["need_full_reocr"]
                    raw_paras = item["paragraphs"]
                    if title in remaining_titles:
                        remaining_titles.remove(title)

                    ent = by_page.get(p_no)
                    if (ent is None or ent.get("type") == "illustration" or need_reocr) and raw_paras:
                        new_paras = []
                        has_title_in_paras = False
                        t_key = _plain_key(title)
                        for r_idx, r_txt in enumerate(raw_paras):
                            clean_r = strip_ft_tags(r_txt).strip()
                            if not clean_r:
                                continue
                            is_t = (_plain_key(clean_r) == t_key) or (r_idx == 0 and len(clean_r) <= 65 and _plain_key(clean_r) in t_key)
                            if is_t and not has_title_in_paras:
                                new_paras.append(
                                    OCRParagraph(
                                        spans=[TextSpan(title, True)],
                                        is_heading=True,
                                        heading_level=1,
                                        block_type="chapter_heading",
                                        reading_order=len(new_paras),
                                    )
                                )
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
                            new_paras.insert(
                                0,
                                OCRParagraph(
                                    spans=[TextSpan(title, True)],
                                    is_heading=True,
                                    heading_level=1,
                                    block_type="chapter_heading",
                                    reading_order=0,
                                ),
                            )
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
                            tp.is_heading = True
                            tp.heading_level = 1
                            tp.block_type = "chapter_heading"
                            tp.spans = [TextSpan(title, tp.is_all_bold)]
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

                    recovered_total += 1
                    self.log.emit(f"[누락 목차 이미지 복구] p{p_no}: '{title}'" + (f" ({item['reason']})" if item.get("reason") else ""))

            self.progress_stage.emit(f"5/5 누락 목차 구간 이미지 탐색 ({iv_idx}/{len(intervals)})")
            self.progress.emit(iv_idx, len(intervals))

        if recovered_total > 0:
            ordered = deduplicate_entries(sorted(ordered, key=lambda entry: int(entry.get("page_no", 0))))
            save_ocr_backup(backup_dir, ordered)
            _, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
            self.log.emit(f"누락 목차 복구 완료: {recovered_total}개 장 추가 · 총 {len(chapters)}개 장으로 EPUB 재생성")
        return ordered, chapters

    def _run_final_gemini_check(self, transcriber, entries, chapters, epub_path, part_meta_by_page, original_loader, backup_dir):
        ordered = deduplicate_entries(sorted(entries, key=lambda entry: int(entry.get("page_no", 0))))
        design = EpubDesignConfig.from_dict(self.opts.epub_design or {})
        design.writing_mode = self.opts.epub_writing_mode
        design.scene_break_style = self.opts.scene_break_style
        checks = []
        for enabled, key in (
            (self.opts.gemini_review_ocr, "ocr"),
            (self.opts.gemini_review_paragraphs, "paragraphs"),
            (self.opts.gemini_review_headings, "headings"),
            (self.opts.gemini_review_toc, "toc"),
            (self.opts.gemini_review_duplicates, "duplicates"),
            (self.opts.gemini_review_illustrations, "illustrations"),
        ):
            if enabled:
                checks.append(key)
        content_checks = [key for key in checks if key != "illustrations"]
        if self.opts.gemini_final_review and content_checks:
            max_passes = max(1, min(3, int(self.opts.gemini_review_passes)))
            for pass_no in range(1, max_passes + 1):
                if self._cancelled:
                    return
                review_pages = []
                for entry in ordered:
                    if entry.get("type") != "text":
                        continue
                    paragraphs = entry.get("paragraphs", [])
                    text = self._paragraphs_to_editable_text(paragraphs)
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
                est_batches = max(1, (len(review_pages) + 11) // 12)
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
                    )
                    self._emit_token_usage(transcriber)
                except InterruptedError:
                    return
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
                    if not _is_safe_content_correction(old_text, new_text):
                        self.log.emit(f"[수정 제외 · 창작/변형 차단] p{page_no}: 원문 글자 변형이나 임의 문장 보완이 커 반영하지 않음")
                        continue
                    prev_heading_map = {
                        _plain_key(p.plain_text): (p.is_heading, p.heading_level, p.block_type, p.is_toc_candidate, p.is_toc_entry)
                        for p in old_paras
                        if p.plain_text.strip()
                    }
                    new_paras = self._editable_text_to_paragraphs(new_text)
                    for np_obj in new_paras:
                        k = _plain_key(np_obj.plain_text)
                        if k in prev_heading_map:
                            ih, hl, bt, itc, ite = prev_heading_map[k]
                            if ih and not np_obj.is_heading:
                                np_obj.is_heading = ih
                                np_obj.heading_level = hl
                                np_obj.block_type = bt
                            if itc:
                                np_obj.is_toc_candidate = True
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
                entries[:] = ordered
                save_ocr_backup(backup_dir, ordered)
                epub_out, chapters = export_light_novel(DIR_OUT, epub_path.stem, ordered, epub_path, self.opts.save_txt_folder, True, design)
                self.log.emit(f"최종 검수 수정 적용 완료: {changed}페이지 수정 · EPUB 재생성")
                if self._cancelled:
                    return
        if not self.opts.gemini_final_review:
            self.log.emit("Gemini 최종 검수가 설정에서 비활성화되어 있습니다.")
            return
        if self.opts.gemini_review_toc or self.opts.gemini_review_headings:
            ordered, chapters = self._reconcile_toc_headings(transcriber, ordered, chapters, epub_path, original_loader, backup_dir, design)
            entries[:] = ordered
            if self._cancelled:
                return
            ordered, chapters = self._recover_missing_toc_chapters(transcriber, ordered, chapters, epub_path, part_meta_by_page, original_loader, backup_dir, design)
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
                toc_markers = {"目次", "もくじ", "목차", "차례", "contents", "table of contents"}
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
                text = item.get("text", "")
                if item_type == "toc_entry":
                    text = "".join(span.text for span in item.get("spans", []))
                items.append({"type": item_type, "page": int(item.get("page_no", 0)), "level": int(item.get("level", 0)), "text": str(text)[:90]})
            chapter_summaries.append({"order": chapter_index, "title": chapter.title, "in_navigation": bool(chapter.title), "items": items})
        self.progress.emit(1, 3)
        local_issues = []
        if duplicate_fingerprints:
            local_issues.append("중복 원본 이미지 지문이 남아 있습니다: " + str(duplicate_fingerprints[:12]))
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
            issues = transcriber.audit_epub_structure(
                page_summaries,
                chapter_summaries,
                epub_structure,
                contact_sheet=contact_sheet,
                toc_images=toc_images,
                cancelled_fn=lambda: self._cancelled,
                log_cb=self.log.emit,
            )
            self._emit_token_usage(transcriber)
            if issues:
                for issue in issues:
                    self.log.emit(f"[Gemini 최종 구조 검수] {issue}")
            else:
                self.log.emit("Gemini 최종 구조 검수: 명확한 구조·순서·목차·크롭 오류가 발견되지 않았습니다.")
        except Exception as exc:
            self.log.emit(f"[Gemini 최종 구조 검수 실패] {exc}")
        self.progress.emit(3, 3)
        for issue in local_issues:
            self.log.emit(f"[로컬 검사] {issue}")
        self.log.emit("최종 검수 완료: 적용 가능한 본문 수정은 OCR 백업과 EPUB에 반영됨")