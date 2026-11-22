import io
import json
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image

from core.gemini.markup import _is_json_parse_error
from core.gemini.review.base import _HANGUL_RE, is_retryable_review_error


class MissingTocMixin:
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
            "4. 添付画像またはOCRテキスト上にmissing_titlesの章タイトル文字列が実際に印刷・描画されているページだけをfoundに入れてください。(3/43)のような番号表記や物語の文脈だけから章の開始を推測・捏造することは絶対禁止です。該当ページがなければfoundは空配列[]を返してください。reasonは必ず韓国語（한국어）で記述してください。\n"
        ) + self._extra_prompt("prompt_extra_missing_toc") + "DATA: "

        def run_range_resilient(sub_meta: List[Dict], sub_imgs: List[Tuple[int, Image.Image]], label: str) -> List[Dict]:
            payload = {"missing_titles": missing_titles, "pages": sub_meta}
            config = self._make_config(types, 0.0, 16384, schema, "HIGH")
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
                if can_split and (_is_json_parse_error(exc) or is_retryable_review_error(exc)):
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
