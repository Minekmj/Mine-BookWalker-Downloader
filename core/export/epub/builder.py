import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from core.export.epub.chapter_render import ImageRegistry, render_chapter_xhtml
from core.export.epub.chapters import EpubChapter
from core.export.epub.packaging import (
    build_cover_xhtml,
    build_nav_xhtml,
    build_navigation_points,
    build_ncx,
    build_package_documents,
    write_epub_archive,
)
from core.export.epub.patterns import TOC_TITLE_RE
from core.export.epub.styles import EpubDesignConfig, generate_epub_css
from core.export.epub.text_utils import _plain_key, _xml_safe
from core.export.epub.validator import validate_epub_package
from core.vision.image_utils import load_entry_image


def _extract_cover(chapters: List[EpubChapter], cfg: EpubDesignConfig):
    has_cover = bool(chapters and cfg.cover_enabled and chapters[0].items and chapters[0].items[0].get("type") == "illustration" and chapters[0].items[0].get("is_cover", False) and chapters[0].items[0].get("page_no") == 1)
    cover_item = None
    if has_cover:
        cover_item = chapters[0].items.pop(0)
        if not chapters[0].items:
            chapters = chapters[1:]
    return has_cover, cover_item, chapters


def build_epub(epub_path: Path, book_title: str, chapters: List[EpubChapter], design: Optional[EpubDesignConfig] = None):
    epub_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = design or EpubDesignConfig()
    book_uuid = str(uuid.uuid4())
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_title = _xml_safe(book_title or "Novel")
    chapters = [EpubChapter(chapter.title or "", list(chapter.items), hide_heading=chapter.hide_heading) for chapter in chapters]
    chapters = [chapter for chapter in chapters if chapter.items]
    has_cover, cover_item, chapters = _extract_cover(chapters, cfg)

    chapter_info = []
    title_targets = {}
    for index, chapter in enumerate(chapters, start=1):
        filename = f"chap_{index:03d}.xhtml"
        chapter_info.append((filename, chapter))
        key = _plain_key(chapter.title)
        if key and key not in title_targets:
            title_targets[key] = f"{filename}#chapter-title"

    registry = ImageRegistry()
    if has_cover and cover_item is not None:
        cover_image = load_entry_image(cover_item)
        if cover_image is not None:
            registry.add_cover(cover_image)

    chapter_xhtml = []
    chapter_subsections = {}
    for chapter_index, (filename, chapter) in enumerate(chapter_info, start=1):
        xhtml, subsections = render_chapter_xhtml(chapter, chapter_index, title_targets, registry, register_dividers=cfg.register_dividers_in_toc)
        if xhtml is None:
            continue
        chapter_xhtml.append((filename, str(chapter.title or "").strip(), xhtml))
        chapter_subsections[filename] = subsections

    body_start = next((filename for filename, title, _ in chapter_xhtml if title and not TOC_TITLE_RE.match(title)), chapter_xhtml[0][0] if chapter_xhtml else "")
    nav_items, ncx_points = build_navigation_points(chapter_xhtml, chapter_subsections)
    cover_file = ("Text/cover.xhtml", "Cover", build_cover_xhtml()) if has_cover else None

    nav_xhtml = build_nav_xhtml(nav_items, has_cover, body_start)
    ncx = build_ncx(book_uuid, safe_title, ncx_points)
    opf = build_package_documents(book_uuid, safe_title, modified, has_cover, cover_file, chapter_xhtml, registry.order)
    write_epub_archive(epub_path, opf, ncx, nav_xhtml, generate_epub_css(cfg), cover_file, chapter_xhtml, registry.order)
    validate_epub_package(epub_path)
