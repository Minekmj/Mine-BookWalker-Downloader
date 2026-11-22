import io
import json
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from core.gemini.markup import _is_json_parse_error
from core.gemini.review.base import _HANGUL_RE, is_retryable_review_error


class TocReconcileMixin:
    def reconcile_chapters_and_toc(
        self,
        printed_toc: List[str],
        current_chapters: List[Dict],
        candidates: List[Dict],
        toc_images: Optional[List[Tuple[int, Image.Image]]] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        if not candidates:
            return {"promotions": [], "demotions": []}
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
            "あなたは電子書籍の目次（<title>）・区分者（<bic>）判定および相互修正エンジンです。\n"
            "OCR工程で <title> タグが付いた章タイトル候補（tag_type='title'）、<bic> タグが付いた区分者・小見出し候補（tag_type='bic'）、およびその他の見出し候補（candidates）について、直前の本文（prev_context）と直後の本文（next_context）、さらに印刷目次（printed_tocおよび添付目次画像）や既存の章構成（current_chapters）を照合してください。\n"
            "規則：\n"
            "1. 絶対に他言語（韓国語・英語など）へ翻訳しないでください。chapter_titleは必ず原本どおりの日本語で返してください。\n"
            "2. <title> と <bic> は同じ検収工程で同時に判定し、OCRの初期タグ付けミスは積極的に相互修正してください：\n"
            "   - 独立した章タイトル・大見出し（印刷目次にある見出し、第1章・プロローグ・エピローグ・あとがき・外伝等）は tag_type='bic' であっても heading_level=1（<title>）として promotions に追加してください。\n"
            "   - 本文内の節番号・場面区切り記号・小見出し（例：1, 2, 3, (1/23), 一, 二 等）は tag_type='title' や is_chapter_now=true であっても heading_level=2（<bic>）として promotions に追加してください。単なる数字の「1」「2」「3」等を heading_level=1 にしないでください。\n"
            "   - 印刷目次と一致するにもかかわらず current_chapters から漏れている章（装飾画像のためローマ数字 I, II, VIII, X 等が抜けて「◆ タイトル」等になっている場合を含む）は必ず heading_level=1 で promotions に追加し、chapter_title には印刷目次の正式表記を使用してください。\n"
            "3. 重要：特典SS・番外編・外伝・プロローグ・エピローグ・あとがき・◆記号付き見出しなど、印刷目次に載っていなくても本文の構成上独立した章タイトルであるものは絶対に demotions に入れないでください。\n"
            "4. demotions には、prev_context や next_context の文・会話の途中に埋め込まれているだけの通常の本文が誤って <title>/<bic> 候補や見出しになっている場合のみを入れてください。\n"
            "5. すでに is_chapter_now=true かつ heading_level=1 が妥当で表記も正しい章、またはすでに is_section_now=true かつ heading_level=2 が妥当な区分者は promotions に重複して入れる必要はありません。\n"
            "6. reasonは必ず韓国語（한국어）で記述してください。\n"
        ) + self._extra_prompt("prompt_extra_toc_reconcile") + "DATA: "
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
            config = self._make_config(types, 0.0, 8192, schema, "HIGH")
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
                if len(sub_chunk) > 1 and (_is_json_parse_error(exc) or is_retryable_review_error(exc)):
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
            data = run_chunk_resilient(chunk, f"목차·구분자 문맥 판별 {chunk_idx}/{len(chunks)}", chunk_idx == 1)
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
