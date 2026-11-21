import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.epub.chapters import EpubChapter
from core.epub.text_utils import _image_bytes, _render_spans_html, _xml_safe
from core.epub.toc import find_toc_target
from core.image_utils import load_entry_image


class ImageRegistry:

    def __init__(self):
        self.by_digest: Dict[str, str] = {}
        self.order: List[Tuple[str, bytes, str]] = []
        self.index = 1

    def add_cover(self, image) -> None:
        cover_bytes = _image_bytes(image)
        cover_digest = hashlib.sha256(cover_bytes).hexdigest()
        self.by_digest[cover_digest] = "Images/cover.png"
        self.order.append(("Images/cover.png", cover_bytes, "cover-image"))

    def register_item(self, item: Dict) -> str:
        img_path = item.get("image_path")
        if item.get("image") is not None:
            data = _image_bytes(item["image"])
        elif img_path and Path(img_path).is_file() and Path(img_path).suffix.lower() == ".png":
            data = Path(img_path).read_bytes()
        else:
            img = load_entry_image(item)
            data = _image_bytes(img) if img is not None else b""
        digest = hashlib.sha256(data).hexdigest()
        rel = self.by_digest.get(digest)
        if rel is None:
            rel = f"Images/img_{self.index:04d}.png"
            self.index += 1
            self.by_digest[digest] = rel
            self.order.append((rel, data, ""))
        return rel

    def register(self, image) -> str:
        data = _image_bytes(image)
        digest = hashlib.sha256(data).hexdigest()
        rel = self.by_digest.get(digest)
        if rel is None:
            rel = f"Images/img_{self.index:04d}.png"
            self.index += 1
            self.by_digest[digest] = rel
            self.order.append((rel, data, ""))
        return rel


def _render_items(chapter: EpubChapter, chapter_index: int, title_targets: Dict[str, str], registry: ImageRegistry):
    body = []
    subsections = []
    heading_added = False
    section_index = 0
    for item in chapter.items:
        item_type = item.get("type")
        if item_type == "heading":
            heading_id = "chapter-title" if not heading_added else f"chapter-title-{chapter_index}"
            heading_text = str(item.get("text", chapter.title) or "").strip()
            if heading_text:
                body.append(f'<h1 id="{heading_id}" class="chapter-title">{_xml_safe(heading_text)}</h1>')
                heading_added = True
        elif item_type == "subheading":
            section_index += 1
            level = max(2, min(3, int(item.get("level", 2))))
            tag = "h2" if level == 2 else "h3"
            section_id = f"section-{chapter_index:03d}-{section_index:03d}"
            section_text = str(item.get("text", "") or "").strip()
            if section_text:
                body.append(f'<{tag} id="{section_id}" class="section-title level-{level}">{_xml_safe(section_text)}</{tag}>')
                subsections.append((level, section_id, section_text))
        elif item_type == "scene_break":
            value = item.get("text", "＊　＊　＊")
            body.append('<hr class="scene-hr"/>' if value == "__hr__" else f'<div class="scene-break">{_xml_safe(value)}</div>')
        elif item_type == "illustration":
            image_rel = registry.register_item(item)
            alt = _xml_safe(f"Illustration, page {item.get('page_no', 0)}")
            body.append(f'<div class="illust-wrap"><img src="../{image_rel}" alt="{alt}"/></div>')
        elif item_type == "toc_entry":
            spans = item.get("spans", [])
            text = "".join(span.text for span in spans)
            target = find_toc_target(text, title_targets)
            rendered = _render_spans_html(spans)
            if target:
                rendered = f'<a href="{target}">{rendered}</a>'
            body.append(f'<p class="toc-entry">{rendered}</p>')
        elif item_type == "paragraph":
            spans = item.get("spans", [])
            plain = "".join(span.text for span in spans).lstrip()
            dialogue = plain.startswith(("「", "『", "【", "（", '"', "'"))
            class_attr = ' class="dialogue"' if dialogue else ""
            body.append(f"<p{class_attr}>{_render_spans_html(spans)}</p>")
    return body, subsections, heading_added


def render_chapter_xhtml(chapter: EpubChapter, chapter_index: int, title_targets: Dict[str, str], registry: ImageRegistry) -> Tuple[Optional[str], List]:
    body, subsections, heading_added = _render_items(chapter, chapter_index, title_targets, registry)
    if not heading_added and chapter.title and chapter.title.strip():
        body.insert(0, f'<h1 id="chapter-title" class="chapter-title">{_xml_safe(chapter.title)}</h1>')
    if not body:
        return None, subsections
    chapter_title = str(chapter.title or "").strip()
    xhtml = (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="ja" xml:lang="ja"><head><meta charset="utf-8"/>'
        f'<title>{_xml_safe(chapter_title)}</title><link rel="stylesheet" type="text/css" href="../Styles/styles.css"/>'
        '</head><body>\n' + "\n".join(body) + '\n</body></html>'
    )
    return xhtml, subsections
