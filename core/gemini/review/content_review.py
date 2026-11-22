from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import io
import json
from typing import Callable, Dict, List, Optional

from PIL import Image

from core.gemini.markup import _is_json_parse_error
from core.gemini.review.base import _HANGUL_RE, is_retryable_review_error


class ContentReviewMixin:
    def review_epub_content(
        self,
        pages: List[Dict],
        checks: List[str],
        cancelled_fn: Optional[Callable[[], bool]] = None,
        max_concurrent: int = 4,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        original_loader: Optional[Callable[[int], Optional[Image.Image]]] = None,
        batch_size: int = 15,
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
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "corrected_text", "reason"],
                    },
                },
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["corrections", "issues"],
        }
        check_names = {
            "ocr": "明らかなOCR誤字の最小限の修正",
            "paragraphs": "連結された段落・セリフ・見出しの改行(\\n)復元",
            "headings": "章見出しと小見出しの確認",
            "toc": "目次項目と本文見出しの一致確認",
            "duplicates": "同一page_no内部のみの明らかな重複出力確認（他ページとの比較禁止）",
            "illustrations": "挿絵順序・周辺文脈の確認",
        }
        prompt = (
            "あなたは日本語電子書籍の最終校正担当者です。以下のOCR済みページテキストを校正し、修正が必要なページのみをcorrectionsに返してください。\n"
            "厳守事項（違反禁止）：\n"
            "0. 各page_noは完全に独立して個別に判定してください。他のページ（前後のpage_no）を気にしたり、他ページと文章を繋げたり・比較・移動・統合・重複削除することは絶対禁止です。原文の文章・記号・段落を絶対に毀損・削除・書き換えしないでください。\n"
            "1. ページ冒頭や末尾が文の途中で途切れていても、それは前のページから続いているか次のページへ続いているだけの正常な書籍仕様です。絶対に文脈から続きや前の語句を補完・完結・推測・創作・延長・単語追加・削除・前後ページ間移動しないでください。\n"
            "2. 韓国語・英語など他の言語へ翻訳・変換することは絶対禁止です。出力はすべて日本語のみで行ってください。\n"
            "3. 各page_noのcorrected_textには変更箇所だけを抜粋するのではなく、必ずそのpage_noの最初から最後までの全段落・全文を省略せずに出力してください。元のそのページの文字数をほぼ完全に保ったまま、(a)抜けた改行(\\n)の挿入、および(b)1〜2文字程度の明白な文字化け誤字の最小修正のみを行ってください。場面転換記号・区切り記号・番号表記（例：(1/23)、(1)、1/23、◆、＊、※、─── 等）を「不要」と判断して削除・改変することは絶対禁止です。\n"
            "4. 最重要校正項目 — 段落の改行(\\n)抜けの修正：\n"
            "   needs_paragraph_split=trueのページや、100文字以上の長い塊になっている行を特に注意して確認してください。\n"
            "   (1) 地の文とセリフ（例：……だった。「……」または「……」……だった。）が改行なしで繋がっている場合、\n"
            "   (2) 異なるセリフ（「……」「……」など）が1行に繋がっている場合、\n"
            "   (3) 章見出し・小見出し・場面転換記号が本文と1行に繋がっている場合、\n"
            "   (4) 文末（。/！/？）の後で場面・話題・主語が切り替わり、本来なら段落が分かれるべき箇所で改行が抜けている場合、\n"
            "   必ず適切な境界に改行(\\n)を入れて段落を分割してください。\n"
            "   文字を1文字も変えずに改行(\\n)のみを補う修正も非常に重要ですので、issuesに書くだけで終わらせず、必ずcorrectionsに修正後の全段落を入れて返してください。\n"
            "5. <title>...</title>は章タイトル候補、<bic>...</bic>は区分者・小見出し候補マーカーです。入力テキストに<title>...</title>、<bic>...</bic>、または<b>...</b>が含まれている場合は、修正後もそのまま保持してください（誤って別タグになっていた場合のみ<title>と<bic>を相互修正可）。\n"
            "6. 修正が不要なページはcorrectionsに入れないでください。\n"
            "各ページのJSON直後に添付された原本ページ画像（PAGE <page_no>）と必ず1文字ずつ照合してください。画像に実際には印刷されていないハルシネーション（勝手に補完された文・捏造された語句・順序が入れ替わった文）がJSON内にある場合は、必ず画像に印刷されている正確な内容・順序どおりに修正してください。\n"
            "点検項目: " + " / ".join(check_names.get(item, item) for item in checks) + "。\n"
            "reasonとissuesは必ず簡潔な韓国語（한국어）で記述してください。ただしcorrected_textは必ず原本の日本語のみを出力してください。\n"
            "指定されたJSON形式のみを出力してください。"
        ) + self._extra_prompt("prompt_extra_content_review") + "DATA: "
        batches: List[List[Dict]] = []
        cur_batch: List[Dict] = []
        cur_chars = 0
        max_per_batch = max(1, int(batch_size))
        max_chars = max_per_batch * 1800
        for page in pages:
            p_len = len(str(page.get("text", "")))
            if cur_batch and (len(cur_batch) >= max_per_batch or cur_chars + p_len > max_chars):
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
            contents = [prompt]
            for page in payload:
                p_no = int(page.get("page_no", 0))
                contents.append(f"### PAGE {p_no} ###\n" + json.dumps(page, ensure_ascii=False, separators=(",", ":")))
                if original_loader is not None and p_no > 0:
                    img = original_loader(p_no)
                    if img is not None:
                        thumb = img.convert("RGB")
                        thumb.thumbnail((1100, 1400), Image.Resampling.LANCZOS)
                        buf = io.BytesIO()
                        thumb.save(buf, format="JPEG", quality=85, optimize=True)
                        contents.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
            config = self._make_config(types, 1.0, 32768, schema, "HIGH")
            try:
                data = self._generate_json_with_retry(
                    contents=contents,
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
                if len(payload) > 1 and (_is_json_parse_error(exc) or is_retryable_review_error(exc)):
                    mid = len(payload) // 2
                    if log_cb:
                        log_cb(f"[{label}] 문자열/변환 오류로 분할 재시도 ({len(payload)} -> {mid} + {len(payload) - mid}): {exc}")
                    left = run_payload_resilient(payload[:mid], f"{label}-1")
                    right = run_payload_resilient(payload[mid:], f"{label}-2")
                    return {
                        "corrections": list(left.get("corrections", []) or []) + list(right.get("corrections", []) or []),
                        "issues": list(left.get("issues", []) or []) + list(right.get("issues", []) or []),
                    }
                if len(payload) == 1 and _is_json_parse_error(exc):
                    p_no = payload[0].get("page_no", "?")
                    if log_cb:
                        log_cb(f"[내용 검수 건너뜀] p{p_no}: JSON 파싱 오류로 원문 유지 ({exc})")
                    return {"corrections": [], "issues": []}
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
