import posixpath
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Dict, List
from urllib.parse import unquote


def _validate_links(root: ET.Element, current_path: str, names: set, archive: zipfile.ZipFile, errors: List[str]):
    current_dir = posixpath.dirname(current_path)
    for element in root.iter():
        src = element.attrib.get("src")
        if src:
            path_part, _, fragment = src.partition("#")
            target = posixpath.normpath(posixpath.join(current_dir, unquote(path_part))) if path_part else current_path
            if target not in names:
                errors.append(f"Missing resource: {current_path} -> {src}")
            elif fragment and target.endswith((".xhtml", ".html")):
                target_root = ET.fromstring(archive.read(target))
                if not any(node.attrib.get("id") == fragment for node in target_root.iter()):
                    errors.append(f"Missing resource anchor: {current_path} -> {src}")
        href = element.attrib.get("href")
        if href and not href.startswith(("http://", "https://", "mailto:")):
            path_part, _, fragment = href.partition("#")
            target = posixpath.normpath(posixpath.join(current_dir, unquote(path_part))) if path_part else current_path
            if target not in names:
                errors.append(f"Missing internal link: {current_path} -> {href}")
            elif fragment and target.endswith((".xhtml", ".html")):
                target_root = ET.fromstring(archive.read(target))
                if not any(node.attrib.get("id") == fragment for node in target_root.iter()):
                    errors.append(f"Missing internal link anchor: {current_path} -> {href}")


def validate_epub_package(epub_path: Path) -> Dict[str, List[str]]:
    errors = []
    warnings = []
    with zipfile.ZipFile(epub_path, "r") as archive:
        names = set(archive.namelist())
        if not archive.namelist() or archive.namelist()[0] != "mimetype" or archive.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
            errors.append("The mimetype file must be first and uncompressed.")
        required = {"META-INF/container.xml", "OEBPS/content.opf", "OEBPS/Text/nav.xhtml"}
        missing = required - names
        if missing:
            errors.extend(f"Missing required file: {name}" for name in sorted(missing))
            return {"errors": errors, "warnings": warnings}
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
        manifest = {}
        for node in opf.iter():
            if node.tag.endswith("item"):
                item_id = node.attrib.get("id", "")
                href = node.attrib.get("href", "")
                if item_id in manifest:
                    errors.append(f"Duplicate manifest ID: {item_id}")
                manifest[item_id] = href
                target = posixpath.normpath(posixpath.join("OEBPS", href))
                if target not in names:
                    errors.append(f"Missing manifest resource: {target}")
        spine_ids = [node.attrib.get("idref", "") for node in opf.iter() if node.tag.endswith("itemref")]
        spine_hrefs = [manifest[item_id] for item_id in spine_ids if item_id in manifest]
        if len(spine_hrefs) != len(spine_ids):
            errors.append("An EPUB spine item has no manifest entry.")
        if len(spine_hrefs) != len(set(spine_hrefs)):
            warnings.append("The same XHTML document is registered more than once in the spine.")
        for href in spine_hrefs:
            path = posixpath.normpath(posixpath.join("OEBPS", href))
            root = ET.fromstring(archive.read(path))
            _validate_links(root, path, names, archive, errors)
        for name in archive.namelist():
            if name.endswith((".xml", ".xhtml", ".opf", ".ncx")):
                try:
                    ET.fromstring(archive.read(name))
                except ET.ParseError as exc:
                    errors.append(f"XML error in {name}: {exc}")
        nav_path = "OEBPS/Text/nav.xhtml"
        nav_root = ET.fromstring(archive.read(nav_path))
        nav_ns = {"x": "http://www.w3.org/1999/xhtml", "epub": "http://www.idpf.org/2007/ops"}
        toc_nav = nav_root.find(".//x:nav[@epub:type='toc']", nav_ns)
        if toc_nav is None:
            errors.append("The navigation table of contents is missing.")
        else:
            _validate_links(toc_nav, nav_path, names, archive, errors)
    if errors:
        raise ValueError("EPUB validation failed: " + " / ".join(errors[:20]))
    return {"errors": errors, "warnings": warnings}


def read_epub_structure(epub_path: Path) -> Dict:
    with zipfile.ZipFile(epub_path, "r") as archive:
        opf = ET.fromstring(archive.read("OEBPS/content.opf"))
        manifest = {node.attrib.get("id", ""): node.attrib.get("href", "") for node in opf.iter() if node.tag.rsplit("}", 1)[-1] == "item"}
        spine = [manifest.get(node.attrib.get("idref", ""), "") for node in opf.iter() if node.tag.rsplit("}", 1)[-1] == "itemref"]
        nav = ET.fromstring(archive.read("OEBPS/Text/nav.xhtml"))
        rows = []
        for anchor in nav.iter():
            if anchor.tag.rsplit("}", 1)[-1] == "a":
                rows.append({"title": "".join(anchor.itertext()).strip(), "href": anchor.attrib.get("href", "")})
        return {"spine": spine, "navigation": rows}
