import zipfile
from pathlib import Path
from typing import List

from core.epub.text_utils import _xml_safe
from core.epub.toc import render_nav_sections, section_tree

CONTAINER_XML = ('<?xml version="1.0" encoding="utf-8"?>\n'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')


def build_cover_xhtml() -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" lang="ja" xml:lang="ja"><head><meta charset="utf-8"/><title>Cover</title><link rel="stylesheet" type="text/css" href="../Styles/styles.css"/></head><body class="cover-page"><div class="cover-wrap"><img src="../Images/cover.png" alt="Cover"/></div></body></html>')


def build_navigation_points(chapter_xhtml, chapter_subsections):
    nav_items = []
    ncx_points = []
    play_order = 0
    for filename, title, _ in chapter_xhtml:
        sections = chapter_subsections.get(filename, [])
        nested_html = render_nav_sections(sections, filename)

        def render_ncx_nodes(nodes):
            nonlocal play_order
            output = []
            for node in nodes:
                play_order += 1
                child_content = render_ncx_nodes(node["children"])
                output.append(f'<navPoint id="navPoint-{play_order}" playOrder="{play_order}"><navLabel><text>{_xml_safe(node["title"])}</text></navLabel><content src="Text/{filename}#{node["id"]}"/>{child_content}</navPoint>')
            return "".join(output)

        if title:
            parent_order = play_order + 1
            play_order = parent_order
            child_points = render_ncx_nodes(section_tree(sections))
            nav_items.append(f'<li><a href="{filename}#chapter-title">{_xml_safe(title)}</a>{nested_html}</li>')
            ncx_points.append(f'<navPoint id="navPoint-{parent_order}" playOrder="{parent_order}"><navLabel><text>{_xml_safe(title)}</text></navLabel><content src="Text/{filename}#chapter-title"/>{child_points}</navPoint>')
        elif sections:
            child_points = render_ncx_nodes(section_tree(sections))
            ncx_points.append(child_points)
    return nav_items, ncx_points


def build_nav_xhtml(nav_items: List[str], has_cover: bool, body_start: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja" xml:lang="ja"><head><meta charset="utf-8"/><title>Table of Contents</title><link rel="stylesheet" type="text/css" href="../Styles/styles.css"/></head>'
        '<body epub:type="frontmatter"><nav epub:type="toc" id="toc" role="doc-toc"><h1>Table of Contents</h1><ol>' + ''.join(nav_items) + '</ol></nav>'
        '<nav epub:type="landmarks" id="landmarks" hidden=""><ol>' + ('<li><a epub:type="cover" href="cover.xhtml">Cover</a></li>' if has_cover else '') +
        (f'<li><a epub:type="bodymatter" href="{body_start}">Start of Body</a></li>' if body_start else '') + '</ol></nav></body></html>')


def build_ncx(book_uuid: str, safe_title: str, ncx_points: List[str]) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head>' +
        f'<meta name="dtb:uid" content="urn:uuid:{book_uuid}"/><meta name="dtb:depth" content="3"/><meta name="dtb:totalPageCount" content="0"/><meta name="dtb:maxPageNumber" content="0"/></head>' +
        f'<docTitle><text>{safe_title}</text></docTitle><navMap>{"".join(ncx_points)}</navMap></ncx>')


def build_package_documents(book_uuid: str, safe_title: str, modified: str, has_cover: bool, cover_file, chapter_xhtml, image_order):
    manifest = [
        '<item id="nav" href="Text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="Styles/styles.css" media-type="text/css"/>',
    ]
    spine = []
    if cover_file:
        manifest.append('<item id="cover-page" href="Text/cover.xhtml" media-type="application/xhtml+xml"/>')
        spine.append('<itemref idref="cover-page"/>')
    for index, (filename, _, _) in enumerate(chapter_xhtml, start=1):
        item_id = f"chapter-{index:04d}"
        manifest.append(f'<item id="{item_id}" href="Text/{filename}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{item_id}"/>')
    for index, (image_rel, _, properties) in enumerate(image_order, start=1):
        prop = f' properties="{properties}"' if properties else ""
        manifest.append(f'<item id="image-{index:04d}" href="{image_rel}" media-type="image/png"{prop}/>')
    metadata_cover = '<meta name="cover" content="image-0001"/>' if has_cover else ''
    opf = ('<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="BookId">urn:uuid:{book_uuid}</dc:identifier><dc:title>{safe_title}</dc:title><dc:language>ja</dc:language><meta property="dcterms:modified">{modified}</meta>{metadata_cover}'
        '</metadata><manifest>' + ''.join(manifest) + '</manifest><spine toc="ncx">' + ''.join(spine) + '</spine></package>')
    return opf


def write_epub_archive(epub_path: Path, opf: str, ncx: str, nav_xhtml: str, css: str, cover_file, chapter_xhtml, image_order):
    with zipfile.ZipFile(epub_path, "w") as archive:
        archive.writestr("mimetype", b"application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", CONTAINER_XML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/toc.ncx", ncx.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/Text/nav.xhtml", nav_xhtml.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/Styles/styles.css", css.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        if cover_file:
            archive.writestr(f"OEBPS/{cover_file[0]}", cover_file[2].encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        for filename, _, xhtml in chapter_xhtml:
            archive.writestr(f"OEBPS/Text/{filename}", xhtml.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        for image_rel, data, _ in image_order:
            archive.writestr(f"OEBPS/{image_rel}", data, compress_type=zipfile.ZIP_DEFLATED)
