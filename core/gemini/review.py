from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import io
import json
import re
import time
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from core.gemini.markup import _is_json_parse_error, _is_rate_limit_error

_HANGUL_RE = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]")


def _is_retryable_review_error(exc: Exception) -> bool:
    if _is_json_parse_error(exc):
        return True
    s = str(exc).lower()
    tokens = (
        "503", "unavailable", "high demand", "overloaded",
        "500", "502", "504", "internal",
        "429", "resource_exhausted", "rate limit", "quota", "too many requests",
        "timeout", "timed out", "connection", "reset", "temporarily",
        "empty", "비어", "expecting value", "unterminated", "json",
    )
    return any(tok in s for tok in tokens)


class ReviewMixin:

    def _sleep_cancelable(self, seconds: float, cancelled_fn: Optional[Callable[[], bool]] = None):
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if cancelled_fn and cancelled_fn():
                raise InterruptedError("취소됨")
            time.sleep(min(0.25, max(0.01, deadline - time.monotonic())))

    def _generate_json_with_retry(
        self,
        contents,
        config,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        label: str = "검수",
        max_attempts: Optional[int] = None,
        fast_fail_on_json_error: bool = False,
    ):
        attempts = max(1, int(max_attempts if max_attempts is not None else self.max_retries))
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            if cancelled_fn and cancelled_fn():
                raise InterruptedError("취소됨")
            try:
                response = self.pool.generate(
                    cancelled_fn=cancelled_fn,
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
                raw = (getattr(response, "text", None) or "").strip()
                if not raw:
                    raise ValueError("Gemini 검수 응답이 비어 있습니다.")
                match = re.search(r"\{[\s\S]*\}", raw)
                return json.loads(match.group(0) if match else raw)
            except InterruptedError:
                raise
            except Exception as exc:
                last_exc = exc
                if fast_fail_on_json_error and _is_json_parse_error(exc):
                    raise
                if attempt >= attempts or not _is_retryable_review_error(exc):
                    raise
                if _is_rate_limit_error(exc):
                    if log_cb:
                        log_cb(f"[{label}] 할당량 대기 후 재시도 ({attempt}/{attempts})")
                else:
                    if log_cb:
                        log_cb(f"[{label}] 일시 오류로 재시도 ({attempt}/{attempts}): {exc}")
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("검수 요청 실패")

    def review_epub_content(
        self,
        pages: List[Dict],
        checks: List[str],
        cancelled_fn: Optional[Callable[[], bool]] = None,
        max_concurrent: int = 4,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        from google.genai import types
        schema = {
            "type": "OBJECT",
            "properties": {
                "corrections": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "page_no": {"type": "INTEGER"},
                            "corrected_text": {"type": "STRING"},
                            "reason": {"type": "STRING"}
                        },
                        "required": ["page_no", "corrected_text", "reason"]
                    }
                },
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}}
            },
            "required": ["corrections", "issues"]
        }
        check_names = {
            "ocr": "明らかなOCR誤字の最小限の修正",
            "paragraphs": "連結された段落・セリフ・見出しの改行(\\n)復元",
            "headings": "章見出しと小見出しの確認",
            "toc": "目次項目と本文見出しの一致確認",
            "duplicates": "ページ内の明らかな重複文の確認",
            "illustrations": "挿絵順序・周辺文脈の確認"
        }
        prompt = (
            "あなたは日本語電子書籍の最終校正担当者です。以下のOCR済みページテキストを校正し、修正が必要なページのみをcorrectionsに返してください。\n"
            "厳守事項（違反禁止）：\n"
            "1. ページ冒頭や末尾が文の途中で途切れていても、それは前のページから続いているか次のページへ続いているだけの正常な書籍仕様です。絶対に文脈から続きや前の語句を補完・推測・創作・延長・前後ページ間移動しないでください。\n"
            "2. 韓国語・英語など他の言語へ翻訳・変換することは絶対禁止です。出力はすべて日本語のみで行ってください。\n"
            "3. 各page_noのcorrected_textは、元のそのページの文字数をほぼ完全に保ったまま、(a)抜けた改行(\\n)の挿入、および(b)1〜2文字程度の明白な文字化け誤字の最小修正のみを行ってください。\n"
            "4. 最重要校正項目 — 段落の改行(\\n)抜けの修正：\n"
            "   needs_paragraph_split=trueのページや、100文字以上の長い塊になっている行を特に注意して確認してください。\n"
            "   (1) 地の文とセリフ（例：……だった。「……」または「……」……だった。）が改行なしで繋がっている場合、\n"
            "   (2) 異なるセリフ（「……」「……」など）が1行に繋がっている場合、\n"
            "   (3) 章見出し・小見出し・場面転換記号が本文と1行に繋がっている場合、\n"
            "   (4) 文末（。/！/？）の後で場面・話題・主語が切り替わり、本来なら段落が分かれるべき箇所で改行が抜けている場合、\n"
            "   必ず適切な境界に改行(\\n)を入れて段落を分割してください。\n"
            "   文字を1文字も変えずに改行(\\n)のみを補う修正も非常に重要ですので、issuesに書くだけで終わらせず、必ずcorrectionsに修正後の全段落を入れて返してください。\n"
            "5. <ft>...</ft>タグは目次・見出し候補マーカーです。入力テキストに<ft>...</ft>または<b>...</b>が含まれている場合は、修正後もそのまま保持してください。\n"
            "6. 修正が不要なページはcorrectionsに入れないでください。\n"
            "点検項目: " + " / ".join(check_names.get(item, item) for item in checks) + "。\n"
            "issuesには構造上確認が必要な問題のみを簡潔に日本語で記録してください。\n"
            "指定されたJSON形式のみを出力してください。DATA: "
        )
        batches: List[List[Dict]] = []
        cur_batch: List[Dict] = []
        cur_chars = 0
        for page in pages:
            p_len = len(str(page.get("text", "")))
            if cur_batch and (len(cur_batch) >= 12 or cur_chars + p_len > 9000):
                batches.append(cur_batch)
                cur_batch = []
                cur_chars = 0
            cur_batch.append(page)
            cur_chars += p_len
        if cur_batch:
            batches.append(cur_batch)

        if not batches:
            return {"corrections": [], "issues": []}
        total_batches = len(batches)
        results_by_idx: List[Optional[Dict]] = [None] * total_batches
        failed_indices: List[int] = []
        key_cap = max(1, self.pool.slot_count() * 2) if hasattr(self.pool, "slot_count") else 2
        workers = max(1, min(key_cap, int(max_concurrent), total_batches))
        done_count = 0

        def run_payload_resilient(payload: List[Dict], label: str) -> Dict:
            config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=32768, response_mime_type="application/json", response_schema=schema)
            try:
                data = self._generate_json_with_retry(
                    contents=prompt + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    config=config,
                    cancelled_fn=cancelled_fn,
                    log_cb=log_cb,
                    label=label,
                    fast_fail_on_json_error=len(payload) > 1,
                )
                return data if isinstance(data, dict) else {"corrections": [], "issues": []}
            except InterruptedError:
                raise
            except Exception as exc:
                if len(payload) > 1 and (_is_json_parse_error(exc) or _is_retryable_review_error(exc)):
                    mid = len(payload) // 2
                    if log_cb:
                        log_cb(f"[{label}] 문자열/변환 오류로 분할 재시도 ({len(payload)} -> {mid} + {len(payload) - mid}): {exc}")
                    left = run_payload_resilient(payload[:mid], f"{label}-1")
                    right = run_payload_resilient(payload[mid:], f"{label}-2")
                    return {
                        "corrections": list(left.get("corrections", []) or []) + list(right.get("corrections", []) or []),
                        "issues": list(left.get("issues", []) or []) + list(right.get("issues", []) or []),
                    }
                raise

        def run_batch(batch_idx: int, payload: List[Dict]):
            data = run_payload_resilient(payload, f"내용 검수 {batch_idx + 1}/{total_batches}")
            return batch_idx, data

        ex = ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_idx = {ex.submit(run_batch, idx, batch): idx for idx, batch in enumerate(batches)}
            pending = set(future_to_idx.keys())
            while pending:
                if cancelled_fn and cancelled_fn():
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise InterruptedError("취소됨")
                done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                for fut in done:
                    b_idx = future_to_idx[fut]
                    try:
                        batch_idx, data = fut.result()
                        results_by_idx[batch_idx] = data if isinstance(data, dict) else {}
                    except InterruptedError:
                        raise
                    except Exception as exc:
                        failed_indices.append(b_idx)
                        if log_cb:
                            log_cb(f"[내용 검수 {b_idx + 1}/{total_batches} 실패 · 추후 재시도 예정] {exc}")
                    done_count += 1
                    if progress_cb:
                        progress_cb(done_count, total_batches)
        except BaseException:
            ex.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            ex.shutdown(wait=True)

        if failed_indices and not (cancelled_fn and cancelled_fn()):
            if log_cb:
                log_cb(f"[내용 검수 실패 배치 복구 재시도] {len(failed_indices)}개 배치 재시도")
            for b_idx in failed_indices:
                if cancelled_fn and cancelled_fn():
                    break
                try:
                    _, data = run_batch(b_idx, batches[b_idx])
                    results_by_idx[b_idx] = data if isinstance(data, dict) else {}
                    if log_cb:
                        log_cb(f"[내용 검수 {b_idx + 1}/{total_batches} 복구 성공]")
                except InterruptedError:
                    raise
                except Exception as exc:
                    if log_cb:
                        log_cb(f"[내용 검수 {b_idx + 1}/{total_batches} 최종 실패] {exc}")

        all_corrections = []
        all_issues = []
        for data in results_by_idx:
            if isinstance(data, dict):
                all_corrections.extend(data.get("corrections", []) or [])
                all_issues.extend(str(issue).strip() for issue in data.get("issues", []) or [] if str(issue).strip())

        page_orig_map = {int(page.get("page_no", 0)): str(page.get("text", "")) for page in pages}
        corrections = []
        seen = set()
        for item in all_corrections:
            if not isinstance(item, dict):
                continue
            try:
                page_no = int(item.get("page_no", 0))
            except (TypeError, ValueError):
                continue
            if page_no not in page_orig_map or page_no in seen:
                continue
            corrected = str(item.get("corrected_text", "")).strip()
            if not corrected:
                continue
            orig_txt = page_orig_map[page_no]
            if not _HANGUL_RE.search(orig_txt) and _HANGUL_RE.search(corrected):
                if log_cb:
                    log_cb(f"[번역 차단] p{page_no}: 검수 결과에 한국어가 포함되어 반영하지 않음")
                continue
            corrections.append({"page_no": page_no, "corrected_text": corrected, "reason": str(item.get("reason", "")).strip()})
            seen.add(page_no)
        return {"corrections": corrections, "issues": list(dict.fromkeys(all_issues))[:30]}

    def reconcile_chapters_and_toc(
        self,
        printed_toc: List[str],
        current_chapters: List[Dict],
        candidates: List[Dict],
        toc_images: Optional[List[Tuple[int, Image.Image]]] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, List[Dict]]:
        from google.genai import types
        schema = {
            "type": "OBJECT",
            "properties": {
                "promotions": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "page_no": {"type": "INTEGER"},
                            "para_index": {"type": "INTEGER"},
                            "chapter_title": {"type": "STRING"},
                            "heading_level": {"type": "INTEGER"},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "para_index", "chapter_title", "heading_level", "reason"],
                    },
                },
                "demotions": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "page_no": {"type": "INTEGER"},
                            "para_index": {"type": "INTEGER"},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "para_index", "reason"],
                    },
                },
            },
            "required": ["promotions", "demotions"],
        }
        prompt = (
            "あなたは電子書籍の目次・小見出し判定および再構成エンジンです。\n"
            "OCR工程で見出し候補として<ft>...</ft>タグが付いた項目（from_ft=true）およびその他の見出し候補（candidates）について、直前の本文（prev_context）と直後の本文（next_context）、さらに印刷目次（printed_tocおよび添付目次画像）や既存の章構成（current_chapters）を照合してください。\n"
            "規則：\n"
            "1. 絶対に他言語（韓国語・英語など）へ翻訳しないでください。chapter_titleは必ず原本どおりの日本語で返してください。\n"
            "2. 各候補のprev_contextとnext_contextを読み、独立した章タイトル・小見出しか判定してください。\n"
            "   - 直前と直後の本文から独立した見出し（章や節の開始）ならpromotionsに追加してください（大見出しはheading_level=1、節見出しはheading_level=2）。\n"
            "   - 印刷目次と一致するにもかかわらずcurrent_chaptersから漏れている章（装飾画像のためローマ数字 I, II, VIII, X 等が抜けて「◆ タイトル」等になっている場合を含む）は必ずpromotionsに追加し、chapter_titleには印刷目次の正式表記を使用してください。\n"
            "3. 重要：特典SS・番外編・外伝・プロローグ・エピローグ・あとがき・◆記号付き見出しなど、印刷目次に載っていなくても本文の構成上独立した章タイトルであるものは絶対にdemotionsに入れないでください。\n"
            "4. demotionsには、prev_contextやnext_contextの文・会話の途中に埋め込まれているだけの通常の本文が誤ってis_chapter_now=trueまたはis_section_now=trueになっている場合のみを入れてください。\n"
            "5. すでにis_chapter_now=trueかつ表記も正しい章はpromotionsに重複して入れる必要はありません。\n"
            "DATA: "
        )
        chunks = [candidates[i:i + 50] for i in range(0, len(candidates), 50)]
        has_hangul_source = any(_HANGUL_RE.search(t) for t in printed_toc) or any(_HANGUL_RE.search(str(c.get("text", ""))) for c in candidates)
        all_promotions: List[Dict] = []
        all_demotions: List[Dict] = []
        seen_promo = set()
        seen_demo = set()

        def run_chunk_resilient(sub_chunk: List[Dict], label: str, include_toc_images: bool) -> Dict:
            payload = {
                "printed_toc": printed_toc,
                "current_chapters": current_chapters,
                "candidates": sub_chunk,
            }
            config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=8192, response_mime_type="application/json", response_schema=schema)
            contents = [prompt + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))]
            if include_toc_images:
                for page_no, image in (toc_images or [])[:4]:
                    buffer = io.BytesIO()
                    image.convert("RGB").save(buffer, format="JPEG", quality=82, optimize=True)
                    contents.append(f"PRINTED TOC SOURCE PAGE {page_no}")
                    contents.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg"))
            try:
                data = self._generate_json_with_retry(
                    contents=contents,
                    config=config,
                    cancelled_fn=cancelled_fn,
                    log_cb=log_cb,
                    label=label,
                    fast_fail_on_json_error=len(sub_chunk) > 1,
                )
                return data if isinstance(data, dict) else {"promotions": [], "demotions": []}
            except InterruptedError:
                raise
            except Exception as exc:
                if len(sub_chunk) > 1 and (_is_json_parse_error(exc) or _is_retryable_review_error(exc)):
                    mid = len(sub_chunk) // 2
                    if log_cb:
                        log_cb(f"[{label}] 문자열/변환 오류로 분할 재시도 ({len(sub_chunk)} -> {mid} + {len(sub_chunk) - mid}): {exc}")
                    left = run_chunk_resilient(sub_chunk[:mid], f"{label}-1", include_toc_images)
                    right = run_chunk_resilient(sub_chunk[mid:], f"{label}-2", include_toc_images)
                    return {
                        "promotions": list(left.get("promotions", []) or []) + list(right.get("promotions", []) or []),
                        "demotions": list(left.get("demotions", []) or []) + list(right.get("demotions", []) or []),
                    }
                raise

        for chunk_idx, chunk in enumerate(chunks, start=1):
            if cancelled_fn and cancelled_fn():
                break
            data = run_chunk_resilient(chunk, f"목차 후보 문맥 판별 {chunk_idx}/{len(chunks)}", chunk_idx == 1)
            if not isinstance(data, dict):
                continue
            for item in data.get("promotions", []) or []:
                if not isinstance(item, dict):
                    continue
                try:
                    page_no = int(item.get("page_no", 0))
                    para_index = int(item.get("para_index", -1))
                    heading_level = max(1, min(2, int(item.get("heading_level", 1) or 1)))
                except (TypeError, ValueError):
                    continue
                title = str(item.get("chapter_title", "")).strip()
                if not has_hangul_source and _HANGUL_RE.search(title):
                    continue
                if page_no > 0 and para_index >= 0 and title and (page_no, para_index) not in seen_promo:
                    seen_promo.add((page_no, para_index))
                    all_promotions.append({
                        "page_no": page_no,
                        "para_index": para_index,
                        "chapter_title": title,
                        "heading_level": heading_level,
                        "reason": str(item.get("reason", "")).strip(),
                    })
            for item in data.get("demotions", []) or []:
                if not isinstance(item, dict):
                    continue
                try:
                    page_no = int(item.get("page_no", 0))
                    para_index = int(item.get("para_index", -1))
                except (TypeError, ValueError):
                    continue
                if page_no > 0 and para_index >= 0 and (page_no, para_index) not in seen_demo and (page_no, para_index) not in seen_promo:
                    seen_demo.add((page_no, para_index))
                    all_demotions.append({
                        "page_no": page_no,
                        "para_index": para_index,
                        "reason": str(item.get("reason", "")).strip(),
                    })
        return {"promotions": all_promotions, "demotions": all_demotions}

    def locate_missing_chapters_in_range(
        self,
        missing_titles: List[str],
        range_pages_meta: List[Dict],
        range_images: Optional[List[Tuple[int, Image.Image]]] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> List[Dict]:
        from google.genai import types
        schema = {
            "type": "OBJECT",
            "properties": {
                "found": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "page_no": {"type": "INTEGER"},
                            "chapter_title": {"type": "STRING"},
                            "para_index": {"type": "INTEGER"},
                            "need_full_reocr": {"type": "BOOLEAN"},
                            "paragraphs": {"type": "ARRAY", "items": {"type": "STRING"}},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "chapter_title", "para_index", "need_full_reocr", "paragraphs", "reason"],
                    },
                }
            },
            "required": ["found"],
        }
        prompt_prefix = (
            "あなたは電子書籍の欠落章見出し特定エンジンです。以下のページ範囲の中に、印刷目次には存在するが現在の章構成から欠落している章見出し（missing_titles）が含まれています。\n"
            "各ページのOCRメタ情報（pages）および添付されているページ原本画像を確認し、それぞれのmissing_titlesが実際に開始する正確なpage_noを特定してください。\n"
            "規則：\n"
            "1. 絶対に他言語（韓国語・英語など）へ翻訳しないでください。chapter_titleおよびparagraphsは必ず原本の日本語のみを返してください。\n"
            "2. 既存のテキストページ内の段落に既にその見出しが含まれている場合（記号やローマ数字だけが抜けていたり、本文と繋がっている場合を含む）は、そのpage_noとpara_indexを返し、need_full_reocr=falseにしてください。本文と繋がって1段落になっている場合は、そのページの見出しと本文を正しく行分けした文字列配列をparagraphsに入れてneed_full_reocr=trueにしても構いません。\n"
            "3. もしそのページが誤って挿絵（type='illustration'）に分類されてOCRがスキップされていた場合や、OCR時に見出し行が完全に抜けていた場合は、添付画像からそのページ内の章見出しと本文（ルビ除外）をすべて正確に日本語で文字起こししてparagraphs配列（1要素=1段落、先頭にchapter_title）で返し、need_full_reocr=true、para_index=0としてください。\n"
            "4. 確実に該当するページが見つかったものだけをfoundに入れて返してください。\n"
            "DATA: "
        )

        def run_range_resilient(sub_meta: List[Dict], sub_imgs: List[Tuple[int, Image.Image]], label: str) -> List[Dict]:
            payload = {
                "missing_titles": missing_titles,
                "pages": sub_meta,
            }
            config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=16384, response_mime_type="application/json", response_schema=schema)
            contents = [prompt_prefix + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))]
            for page_no, image in sub_imgs:
                thumb = image.convert("RGB")
                thumb.thumbnail((1100, 1400), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                thumb.save(buffer, format="JPEG", quality=82, optimize=True)
                contents.append(f"PAGE {page_no}")
                contents.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg"))
            can_split = len(sub_imgs) > 1 or len(sub_meta) > 1
            try:
                data = self._generate_json_with_retry(
                    contents=contents,
                    config=config,
                    cancelled_fn=cancelled_fn,
                    log_cb=log_cb,
                    label=label,
                    fast_fail_on_json_error=can_split,
                )
                return list((data.get("found", []) if isinstance(data, dict) else []) or [])
            except InterruptedError:
                raise
            except Exception as exc:
                if can_split and (_is_json_parse_error(exc) or _is_retryable_review_error(exc)):
                    if len(sub_imgs) > 1:
                        mid = len(sub_imgs) // 2
                        l_imgs, r_imgs = sub_imgs[:mid], sub_imgs[mid:]
                        l_pages = {p for p, _ in l_imgs}
                        r_pages = {p for p, _ in r_imgs}
                        l_meta = [m for m in sub_meta if int(m.get("page_no", 0)) in l_pages]
                        r_meta = [m for m in sub_meta if int(m.get("page_no", 0)) in r_pages]
                    else:
                        mid = len(sub_meta) // 2
                        l_meta, r_meta = sub_meta[:mid], sub_meta[mid:]
                        l_imgs, r_imgs = sub_imgs, sub_imgs
                    if log_cb:
                        log_cb(f"[{label}] 문자열/변환 오류로 분할 재시도: {exc}")
                    return run_range_resilient(l_meta, l_imgs, f"{label}-1") + run_range_resilient(r_meta, r_imgs, f"{label}-2")
                raise

        raw_found = run_range_resilient(range_pages_meta, list(range_images or []), "누락 목차 구간 탐색")
        has_hangul_source = any(_HANGUL_RE.search(t) for t in missing_titles)
        valid_pages = {int(p.get("page_no", 0)) for p in range_pages_meta} | {int(p) for p, _ in (range_images or [])}
        found = []
        seen_titles = set()
        for item in raw_found:
            if not isinstance(item, dict):
                continue
            try:
                page_no = int(item.get("page_no", 0))
                para_index = int(item.get("para_index", 0))
            except (TypeError, ValueError):
                continue
            title = str(item.get("chapter_title", "")).strip()
            if not title or page_no not in valid_pages or title in seen_titles:
                continue
            if not has_hangul_source and _HANGUL_RE.search(title):
                continue
            raw_paras = [str(p).strip() for p in (item.get("paragraphs", []) or []) if str(p).strip()]
            if not has_hangul_source and any(_HANGUL_RE.search(p) for p in raw_paras):
                continue
            seen_titles.add(title)
            found.append({
                "page_no": page_no,
                "chapter_title": title,
                "para_index": max(0, para_index),
                "need_full_reocr": bool(item.get("need_full_reocr", False)),
                "paragraphs": raw_paras,
                "reason": str(item.get("reason", "")).strip(),
            })
        return found

    def audit_epub_structure(
        self,
        page_summaries: List[Dict],
        chapter_summaries: List[Dict],
        epub_structure: Dict,
        contact_sheet: Optional[Image.Image] = None,
        toc_images: Optional[List[Tuple[int, Image.Image]]] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> List[str]:
        from google.genai import types
        payload = {
            "source_pages": page_summaries,
            "chapters": chapter_summaries,
            "saved_epub": epub_structure,
        }
        prompt = (
            "完成した電子書籍の構造のみを検査するチェッカーです。提供されたJSONおよび添付画像のみを使用し、再OCRや文章の修正・挿絵分類の変更・座標返却は行わないでください。\n"
            "検査項目は4点です。(1) source_pagesのページ番号とillustration_orderが原本順になっているか、(2) ページ・本文・目次・章見出し・小見出しに明らかな重複や順序逆転がないか、(3) 印刷目次の項目がchaptersの実際のタイトルと一致し、保存されたEPUBのnavigationに対応リンクが存在するか、(4) saved_epubのspineとnavigationの順序がchaptersの順序と一致しているか確認してください。\n"
            "重要例外ルール：\n"
            "- chaptersの中でin_navigation=falseの項目（titleが空の表紙・カラー口絵・前付けチャプター等）はspineに存在してもnavigationには登録されないのが正常なEPUB仕様です。これを順序不一致エラーとして報告しないでください。\n"
            "- 短い繰り返しフレーズ、区切り線、同じ登場人物名、意図的な繰り返し見出しや装飾挿絵は重複エラーではありません。テキストページの重複は同一のpage_fingerprintまたは80文字以上のocr_hashが一致する場合のみ報告してください。ページ番号の飛び番だけを理由にエラーとしないでください。\n"
            "添付された目次画像は印刷目次の実表記とOCRテキストの照合のみに使用してください。添付された挿絵比較シートでは同じ枠内のORIGINALとCROPPEDを比較し、主要な被写体が明らかに切断されたり主要部分が欠損している場合のみ報告してください。単なる余白の違いは問題としないでください。\n"
            "根拠が明確な問題のみを日本語で最大8件報告してください。曖昧な場合は報告しないでください。結果は{\"issues\":[\"...\"]}形式のJSONのみを返し、問題がなければ空配列を返してください。DATA: "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        schema = {"type": "OBJECT", "properties": {"issues": {"type": "ARRAY", "items": {"type": "STRING"}}}, "required": ["issues"]}
        config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=1024, response_mime_type="application/json", response_schema=schema)
        contents = [prompt]
        for page_no, image in toc_images or []:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=78, optimize=True)
            contents.append(f"PRINTED TOC SOURCE PAGE {page_no}")
            contents.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg"))
        if contact_sheet is not None:
            buffer = io.BytesIO()
            contact_sheet.convert("RGB").save(buffer, format="JPEG", quality=78, optimize=True)
            contents.append("ILLUSTRATION CROP CONTACT SHEET; EACH PAIR SHOWS ORIGINAL THEN CROPPED")
            contents.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg"))
        data = self._generate_json_with_retry(
            contents=contents,
            config=config,
            cancelled_fn=cancelled_fn,
            log_cb=log_cb,
            label="최종 구조 검수",
        )
        issues = data.get("issues", []) if isinstance(data, dict) else []
        return [str(issue).strip() for issue in issues if str(issue).strip()][:8]
    def detect_toc_from_illustrations(
        self,
        illust_pages: List[Tuple[int, Image.Image]],
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> List[Dict]:
        if not illust_pages:
            return []
        from google.genai import types
        schema = {
            "type": "OBJECT",
            "properties": {
                "pages": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "page_no": {"type": "INTEGER"},
                            "is_toc": {"type": "BOOLEAN"},
                            "toc_title": {"type": "STRING"},
                            "entries": {"type": "ARRAY", "items": {"type": "STRING"}},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "is_toc", "toc_title", "entries", "reason"],
                    },
                }
            },
            "required": ["pages"],
        }
        prompt = (
            "あなたは電子書籍の挿絵ページから印刷目次（目次 / もくじ / 목차 / Contents）を判定・抽出するエンジンです。\n"
            "添付された各ページ画像（PAGE <page_no>）を確認し、それぞれのpage_noを基準にそのページが目次ページであるか（is_toc）を判定してください。\n"
            "規則：\n"
            "1. 通常の挿絵・口絵・表紙・本文ページはis_toc=false、entries=[]としてください。\n"
            "2. 背景にイラストや装飾があっても、章タイトル一覧やページ番号付きの目次表が印刷されているページはis_toc=trueとしてください。\n"
            "3. is_toc=trueのページについては、目次見出し（例：目次、CONTENTS）をtoc_titleに、各目次項目を上から（縦書きは右から左へ）読み順にentries配列として原本の文字どおりに抽出してください。\n"
            "4. 絶対に他言語（韓国語・英語など）へ翻訳しないでください。ルビ（ふりがな）のみ除外し、原本に印刷された文字のみをそのまま返してください。\n"
            "5. 入力されたすべてのpage_noについて結果をpages配列で返してください。"
        )

        def run_batch_resilient(sub_batch: List[Tuple[int, Image.Image]], label: str) -> List[Dict]:
            config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=8192, response_mime_type="application/json", response_schema=schema)
            contents = [prompt]
            for page_no, image in sub_batch:
                thumb = image.convert("RGB")
                thumb.thumbnail((1100, 1400), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                thumb.save(buffer, format="JPEG", quality=82, optimize=True)
                contents.append(f"PAGE {page_no}")
                contents.append(types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/jpeg"))
            try:
                data = self._generate_json_with_retry(
                    contents=contents,
                    config=config,
                    cancelled_fn=cancelled_fn,
                    log_cb=log_cb,
                    label=label,
                    fast_fail_on_json_error=len(sub_batch) > 1,
                )
                return list((data.get("pages", []) if isinstance(data, dict) else []) or [])
            except InterruptedError:
                raise
            except Exception as exc:
                if len(sub_batch) > 1 and (_is_json_parse_error(exc) or _is_retryable_review_error(exc)):
                    mid = len(sub_batch) // 2
                    if log_cb:
                        log_cb(f"[{label}] 문자열/변환 오류로 분할 재시도 ({len(sub_batch)} -> {mid} + {len(sub_batch) - mid}): {exc}")
                    return run_batch_resilient(sub_batch[:mid], f"{label}-1") + run_batch_resilient(sub_batch[mid:], f"{label}-2")
                raise

        valid_pages = {int(p) for p, _ in illust_pages}
        batches = [illust_pages[i:i + 8] for i in range(0, len(illust_pages), 8)]
        detected: List[Dict] = []
        seen_pages = set()
        for b_idx, batch in enumerate(batches, start=1):
            if cancelled_fn and cancelled_fn():
                break
            rows = run_batch_resilient(batch, f"삽화 목차 판별 {b_idx}/{len(batches)}")
            for item in rows:
                if not isinstance(item, dict):
                    continue
                try:
                    page_no = int(item.get("page_no", 0))
                except (TypeError, ValueError):
                    continue
                if page_no not in valid_pages or page_no in seen_pages:
                    continue
                if not bool(item.get("is_toc", False)):
                    continue
                entries = [str(e).strip() for e in (item.get("entries", []) or []) if str(e).strip()]
                if not entries:
                    continue
                seen_pages.add(page_no)
                detected.append({
                    "page_no": page_no,
                    "is_toc": True,
                    "toc_title": str(item.get("toc_title", "")).strip(),
                    "entries": entries,
                    "reason": str(item.get("reason", "")).strip(),
                })
        return detected
