import io
import json
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from core.gemini.markup import _is_json_parse_error
from core.gemini.review.base import is_retryable_review_error


class IllustTocMixin:
    def detect_toc_from_illustrations(
        self,
        illust_pages: List[Tuple[int, Image.Image]],
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        batch_size: int = 5,
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
                            "kind": {"type": "STRING"},
                            "title": {"type": "STRING"},
                            "entries": {"type": "ARRAY", "items": {"type": "STRING"}},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "kind", "title", "entries", "reason"],
                    },
                }
            },
            "required": ["pages"],
        }
        prompt = (
            "あなたは電子書籍の挿絵ページから目次ページおよび章タイトル扉絵を判定・抽出するエンジンです。\n"
            "添付された各挿絵画像（PAGE <page_no>）を確認し、それぞれのpage_noについてkindを判定してください。\n"
            "規則：\n"
            "1. 通常の挿絵・口絵・表紙など、目次でも章見出しでもない画像はkind=\"none\", title=\"\", entries=[]としてください。\n"
            "2. 章タイトル一覧（目次表）が印刷されたページはkind=\"toc_list\"、titleに目次見出し（例：目次）、entriesに各目次項目を上から（縦書きは右から左へ）読み順で入れてください。ページ番号がなくても目次一覧ならtoc_listです。\n"
            "3. 背景やイラストとともに「プロローグ」「第1章 ○○」「I ◆ ○○」「エピローグ」「あとがき」「番外編」など単一の章・節タイトルが描かれている扉絵はkind=\"chapter_title\"、titleにその章タイトルのみを原本の文字どおりに入れ、entries=[]としてください。\n"
            "4. 絶対に他言語（韓国語・英語など）へ翻訳しないでください。ルビ（ふりがな）のみ除外し、原本に印刷された文字のみを返してください。\n"
            "5. 入力されたすべてのpage_noについて結果をpages配列で返してください。reasonは必ず韓国語（한국어）で記述してください。"
        ) + self._extra_prompt("prompt_extra_illust_toc")

        def run_batch_resilient(sub_batch: List[Tuple[int, Image.Image]], label: str) -> List[Dict]:
            config = self._make_config(types, 0.0, 8192, schema, "HIGH")
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
                if len(sub_batch) > 1 and (_is_json_parse_error(exc) or is_retryable_review_error(exc)):
                    mid = len(sub_batch) // 2
                    if log_cb:
                        log_cb(f"[{label}] 문자열/변환 오류로 분할 재시도 ({len(sub_batch)} -> {mid} + {len(sub_batch) - mid}): {exc}")
                    return run_batch_resilient(sub_batch[:mid], f"{label}-1") + run_batch_resilient(sub_batch[mid:], f"{label}-2")
                raise

        valid_pages = {int(p) for p, _ in illust_pages}
        bs = max(1, int(batch_size))
        batches = [illust_pages[i:i + bs] for i in range(0, len(illust_pages), bs)]
        detected: List[Dict] = []
        seen_pages = set()
        for b_idx, batch in enumerate(batches, start=1):
            if cancelled_fn and cancelled_fn():
                break
            rows = run_batch_resilient(batch, f"삽화 목차 후보 판별 {b_idx}/{len(batches)}")
            if progress_cb:
                progress_cb(b_idx, len(batches))
            for item in rows:
                if not isinstance(item, dict):
                    continue
                try:
                    page_no = int(item.get("page_no", 0))
                except (TypeError, ValueError):
                    continue
                if page_no not in valid_pages or page_no in seen_pages:
                    continue
                kind = str(item.get("kind", "none") or "none").strip().lower()
                title = str(item.get("title", "")).strip()
                entries = [str(e).strip() for e in (item.get("entries", []) or []) if str(e).strip()]
                if kind == "toc_list" and entries:
                    seen_pages.add(page_no)
                    detected.append({
                        "page_no": page_no,
                        "kind": "toc_list",
                        "toc_title": title or "目次",
                        "entries": entries,
                        "reason": str(item.get("reason", "")).strip(),
                    })
                elif kind == "chapter_title" and title:
                    seen_pages.add(page_no)
                    detected.append({
                        "page_no": page_no,
                        "kind": "chapter_title",
                        "title": title,
                        "entries": [],
                        "reason": str(item.get("reason", "")).strip(),
                    })
        return detected

    def validate_illustration_chapter_titles(
        self,
        candidates: List[Dict],
        existing_chapters: List[Dict],
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> List[Dict]:
        if not candidates:
            return []
        from google.genai import types
        schema = {
            "type": "OBJECT",
            "properties": {
                "approved": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "page_no": {"type": "INTEGER"},
                            "chapter_title": {"type": "STRING"},
                            "reason": {"type": "STRING"},
                        },
                        "required": ["page_no", "chapter_title", "reason"],
                    },
                }
            },
            "required": ["approved"],
        }
        prompt = (
            "あなたは電子書籍の挿絵由来・目次候補の文脈判定エンジンです。\n"
            "各候補（candidates）は挿絵画像から抽出された章タイトル候補（page_no, title）です。直前の本文（prev_context）と直後の本文（next_context）、および既存の章一覧（existing_chapters）を確認し、その挿絵位置で新しい章として分割するのが自然かつ妥当か判定してください。\n"
            "規則：\n"
            "1. 前後の文脈（prev_contextの終わりとnext_contextの始まり）が場面転換や新章開始として自然であればapprovedに含めてください。\n"
            "2. 会話の途中や一文の途中など明らかに不自然な挿絵キャプションや装飾文字は除外してください。\n"
            "3. chapter_titleは原本どおりの日本語のみを返し、絶対に翻訳しないでください。reasonは必ず韓国語（한국어）で記述してください。\n"
        ) + self._extra_prompt("prompt_extra_illust_toc") + "DATA: "
        payload = {"existing_chapters": existing_chapters, "candidates": candidates}
        config = self._make_config(types, 0.0, 4096, schema, "HIGH")
        data = self._generate_json_with_retry(
            contents=prompt + json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            config=config,
            cancelled_fn=cancelled_fn,
            log_cb=log_cb,
            label="삽화 목차 후보 문맥 검증",
        )
        valid_pages = {int(c.get("page_no", 0)) for c in candidates}
        approved = []
        seen = set()
        for item in (data.get("approved", []) if isinstance(data, dict) else []) or []:
            if not isinstance(item, dict):
                continue
            try:
                p_no = int(item.get("page_no", 0))
            except (TypeError, ValueError):
                continue
            title = str(item.get("chapter_title", "")).strip()
            if p_no in valid_pages and p_no not in seen and title:
                seen.add(p_no)
                approved.append({"page_no": p_no, "chapter_title": title, "reason": str(item.get("reason", "")).strip()})
        return approved
