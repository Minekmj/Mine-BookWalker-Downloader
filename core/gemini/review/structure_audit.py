import io
import json
from typing import Callable, Dict, List, Optional, Tuple

from PIL import Image


class StructureAuditMixin:
    def audit_epub_structure(
        self,
        page_summaries: List[Dict],
        chapter_summaries: List[Dict],
        epub_structure: Dict,
        contact_sheet: Optional[Image.Image] = None,
        toc_images: Optional[List[Tuple[int, Image.Image]]] = None,
        cancelled_fn: Optional[Callable[[], bool]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict:
        from google.genai import types
        payload = {
            "source_pages": page_summaries,
            "chapters": chapter_summaries,
            "saved_epub": epub_structure,
        }
        prompt = (
            "完成した電子書籍の構造を検査し、修正可能な構造エラーがあればfixesに修正指示を出力する構造監査エンジンです。\n"
            "検査項目は6点です。(1) source_pagesのページ番号とillustration_orderが原本順になっているか、(2) ページ・本文・目次・章見出し・小見出しに明らかな重複や順序逆転がないか、(3) 印刷目次の項目がchaptersの実際のタイトルと一致し、保存されたEPUBのnavigationに対応リンクが存在するか、(4) saved_epubのspineとnavigationの順序がchaptersの順序と一致しているか、(5) 印刷目次ページが誤って複数の空章（本文段落なしの連続見出し）に分割されていないか、(6) 挿絵由来の章タイトルが原本ページ順どおりに配置され前後本文の文脈と自然につながっているか確認してください。\n"
            "修正指示ルール（fixes）：\n"
            "- 印刷目次に存在しない単なる数字だけの見出し（例：「2」「3」「4」「11」「12」等）や誤って大見出しになっている段落が独立した章としてnavigationに登録されている場合は、demote_headingsにpage_no・text・to_section（節見出しに落とすならtrue、通常段落に戻すならfalse）・reasonを入れてください。\n"
            "- 印刷目次と表記が異なる章タイトルや重複章タイトルがある場合は、rename_chaptersにpage_no・old_title・new_title・reasonを入れてください。\n"
            "重要例外ルール：\n"
            "- chaptersの中でin_navigation=falseの項目（titleが空の表紙・カラー口絵・前付けチャプター等）はspineに存在してもnavigationには登録されないのが正常なEPUB仕様です。\n"
            "- 親章のnavigation内にサブセクション（h2/h3）がネストされるのは正常なEPUB3仕様です。\n"
            "- 短い繰り返しフレーズ、区切り線、同じ登場人物名、意図的な繰り返し見出しや装飾挿絵は重複エラーではありません。テキストページの重複は同一のpage_fingerprintまたは80文字以上のocr_hashが一致する場合のみ報告してください。\n"
            "根拠が明確な問題およびreasonは必ず韓国語（한국어）で記述してください（issuesは最大8件）。"
            + self._extra_prompt("prompt_extra_structure_audit")
            + "DATA: "
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
        schema = {
            "type": "OBJECT",
            "properties": {
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}},
                "fixes": {
                    "type": "OBJECT",
                    "properties": {
                        "demote_headings": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "page_no": {"type": "INTEGER"},
                                    "text": {"type": "STRING"},
                                    "to_section": {"type": "BOOLEAN"},
                                    "reason": {"type": "STRING"},
                                },
                                "required": ["page_no", "text", "to_section", "reason"],
                            },
                        },
                        "rename_chapters": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "page_no": {"type": "INTEGER"},
                                    "old_title": {"type": "STRING"},
                                    "new_title": {"type": "STRING"},
                                    "reason": {"type": "STRING"},
                                },
                                "required": ["page_no", "old_title", "new_title", "reason"],
                            },
                        },
                    },
                    "required": ["demote_headings", "rename_chapters"],
                },
            },
            "required": ["issues", "fixes"],
        }
        config = self._make_config(types, 0.0, 8192, schema, "HIGH")
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
        if not isinstance(data, dict):
            return {"issues": [], "fixes": {"demote_headings": [], "rename_chapters": []}}
        issues = [str(issue).strip() for issue in (data.get("issues", []) or []) if str(issue).strip()][:8]
        fixes = data.get("fixes", {}) if isinstance(data.get("fixes"), dict) else {}
        return {
            "issues": issues,
            "fixes": {
                "demote_headings": list(fixes.get("demote_headings", []) or []),
                "rename_chapters": list(fixes.get("rename_chapters", []) or []),
            },
        }
