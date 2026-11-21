import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Union

from PIL import Image

from core.epub import EpubChapter, _clean_ruby, build_epub, deduplicate_entries, organize_entries_to_chapters, validate_epub_package
from core.epub.styles import EpubDesignConfig
from core.image_utils import load_entry_image, load_image_rgb
from core.ocr_engine import OCRParagraph


def export_manga_zip(pages: Sequence[Union[Image.Image, Path, str]], zip_path: Path, progress_cb: Optional[Callable[[int, int], None]] = None):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(pages)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        for index, item in enumerate(pages, start=1):
            if isinstance(item, (str, Path)):
                path = Path(item)
                if path.suffix.lower() == ".png":
                    archive.write(path, arcname=f"{index:04d}.png")
                else:
                    with load_image_rgb(path) as im:
                        buffer = io.BytesIO()
                        im.save(buffer, format="PNG", compress_level=1)
                        archive.writestr(f"{index:04d}.png", buffer.getvalue())
            else:
                buffer = io.BytesIO()
                (item if item.mode == "RGB" else item.convert("RGB")).save(buffer, format="PNG", compress_level=1)
                archive.writestr(f"{index:04d}.png", buffer.getvalue())
            if progress_cb:
                progress_cb(index, total)


def export_manga_pdf(pages: Sequence[Union[Image.Image, Path, str]], pdf_path: Path, progress_cb: Optional[Callable[[int, int], None]] = None):
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    total = len(pages)
    if total == 0:
        return
    if isinstance(pages[0], (str, Path)):
        def iter_rest():
            for idx, item in enumerate(pages[1:], start=2):
                with Image.open(Path(item)) as im:
                    yield im.convert("RGB")
                if progress_cb:
                    progress_cb(idx, total)

        with Image.open(Path(pages[0])) as first_im:
            first_rgb = first_im.convert("RGB")
            if progress_cb:
                progress_cb(1, total)
            first_rgb.save(pdf_path, save_all=True, append_images=iter_rest(), resolution=100.0)
        return
    rgb_pages = [image if image.mode == "RGB" else image.convert("RGB") for image in pages]
    if progress_cb:
        progress_cb(len(rgb_pages) // 2, len(rgb_pages))
    rgb_pages[0].save(pdf_path, save_all=True, append_images=rgb_pages[1:], resolution=100.0)
    if progress_cb:
        progress_cb(len(rgb_pages), len(rgb_pages))


def save_ocr_backup(backup_dir: Path, entries: List[Dict]):
    backup_dir.mkdir(parents=True, exist_ok=True)
    image_dir = backup_dir / "backup_illustrations"
    image_dir.mkdir(parents=True, exist_ok=True)
    serialized = []
    referenced_images = set()
    for entry in sorted(entries, key=lambda value: int(value.get("page_no", 0))):
        page_no = int(entry["page_no"])
        common = {
            "page_no": page_no,
            "source_name": str(entry.get("source_name", "")),
            "source_key": str(entry.get("source_key", "")),
            "source_part_index": int(entry.get("source_part_index", 0)),
            "page_fingerprint": str(entry.get("page_fingerprint", "")),
            "ocr_version": 4,
        }
        if entry.get("type") == "illustration":
            filename = f"page_{page_no:04d}.png"
            target = image_dir / filename
            image = entry.get("image")
            src_path = entry.get("image_path")
            if image is None and not (src_path and Path(src_path).is_file()):
                continue
            if not (entry.get("_backup_png_saved") and target.is_file()):
                temporary = target.with_suffix(".png.tmp")
                if image is not None:
                    (image if image.mode == "RGB" else image.convert("RGB")).save(temporary, format="PNG", compress_level=1)
                    entry["image_size"] = list(image.size)
                else:
                    src_p = Path(src_path)
                    if src_p.resolve() != target.resolve():
                        shutil.copy2(src_p, temporary)
                if temporary.is_file():
                    temporary.replace(target)
                entry["image_path"] = str(target)
                entry["image"] = None
                entry["_backup_png_saved"] = True
            referenced_images.add(filename)
            serialized.append({**common, "type": "illustration", "reason": str(entry.get("reason", "")), "is_cover": bool(entry.get("is_cover", False)), "chapter_title": str(entry.get("chapter_title", "")), "toc_entries": list(entry.get("toc_entries", []) or []), "image_rel": f"backup_illustrations/{filename}"})
        else:
            serialized.append({**common, "type": "text", "paragraphs": [paragraph.to_dict() for paragraph in entry.get("paragraphs", [])], "ocr_error": str(entry.get("ocr_error", ""))})
    for image_path in image_dir.glob("page_*.png"):
        if image_path.name not in referenced_images:
            image_path.unlink(missing_ok=True)
    temporary = backup_dir / "ocr_backup.json.tmp"
    target = backup_dir / "ocr_backup.json"
    temporary.write_text(json.dumps(serialized, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def load_ocr_backup(backup_json_path: Path) -> List[Dict]:
    backup_dir = backup_json_path.parent
    raw_entries = json.loads(backup_json_path.read_text(encoding="utf-8"))
    entries = []
    for item in raw_entries:
        common = {
            "page_no": int(item.get("page_no", 0)),
            "source_name": str(item.get("source_name", "")),
            "source_key": str(item.get("source_key", "")),
            "source_part_index": int(item.get("source_part_index", 0)),
            "page_fingerprint": str(item.get("page_fingerprint", "")),
            "ocr_version": int(item.get("ocr_version", 1) or 1),
        }
        if item.get("type") == "illustration":
            image_path = (backup_dir / str(item.get("image_rel", ""))).resolve()
            if not image_path.is_file():
                continue
            entries.append({**common, "type": "illustration", "reason": str(item.get("reason", "")), "is_cover": bool(item.get("is_cover", False)), "chapter_title": str(item.get("chapter_title", "")), "toc_entries": [str(x) for x in (item.get("toc_entries", []) or []) if str(x).strip()], "image": None, "image_path": str(image_path), "_backup_png_saved": True})
        else:
            entries.append({
                **common,
                "type": "text",
                "paragraphs": [OCRParagraph.from_dict(paragraph) for paragraph in item.get("paragraphs", [])],
                "ocr_error": str(item.get("ocr_error", "")),
            })
    return sorted(entries, key=lambda value: value["page_no"])


def export_light_novel(output_dir: Path, book_name: str, entries: List[Dict], epub_target_path: Path, save_txt_folder: bool = True, make_epub: bool = True, design: Optional[EpubDesignConfig] = None) -> tuple[Optional[Path], List[EpubChapter]]:
    entries = deduplicate_entries(entries)
    cfg = design or EpubDesignConfig()
    chapters = organize_entries_to_chapters(entries, cfg.scene_break_style)
    epub_out = None
    if make_epub:
        build_epub(epub_target_path, book_name, chapters, cfg)
        validate_epub_package(epub_target_path)
        epub_out = epub_target_path
    if save_txt_folder:
        target_dir = output_dir / book_name
        image_dir = target_dir / "illustrations"
        target_dir.mkdir(parents=True, exist_ok=True)
        image_dir.mkdir(parents=True, exist_ok=True)
        for old in image_dir.glob("*.png"):
            old.unlink(missing_ok=True)
        text_blocks = []
        image_records = []
        image_index = 1
        for chapter in chapters:
            for item in chapter.items:
                item_type = item.get("type")
                if item_type == "heading":
                    text_blocks.append(f"\n=== {_clean_ruby(item.get('text', ''))} ===\n")
                elif item_type == "subheading":
                    text_blocks.append(f"\n--- {_clean_ruby(item.get('text', ''))} ---\n")
                elif item_type == "scene_break":
                    text_blocks.append("\n＊　＊　＊\n")
                elif item_type == "illustration":
                    filename = f"{image_index:03d}_p{int(item.get('page_no', 0)):04d}.png"
                    dst_file = image_dir / filename
                    src_path = item.get("image_path")
                    if item.get("image") is not None:
                        img_obj = item["image"]
                        (img_obj if img_obj.mode == "RGB" else img_obj.convert("RGB")).save(dst_file, format="PNG", compress_level=1)
                    elif src_path and Path(src_path).is_file():
                        shutil.copy2(Path(src_path), dst_file)
                    else:
                        img_obj = load_entry_image(item)
                        if img_obj is not None:
                            img_obj.save(dst_file, format="PNG", compress_level=1)
                    relative = f"illustrations/{filename}"
                    text_blocks.append(f"\n[삽화 #{image_index:03d} | 페이지: {item.get('page_no')} | 파일: {relative}]\n")
                    image_records.append({"order": image_index, "page_no": item.get("page_no"), "file": relative, "source_file": item.get("source_name", ""), "reason": item.get("reason", "")})
                    image_index += 1
                elif item_type in {"paragraph", "toc_entry"}:
                    text = "".join(span.text for span in item.get("spans", []))
                    if text.strip():
                        text_blocks.append(_clean_ruby(text).strip())
        (target_dir / "novel.txt").write_text("\n\n".join(text_blocks), encoding="utf-8")
        (target_dir / "illustrations_order.json").write_text(json.dumps(image_records, ensure_ascii=False, indent=2), encoding="utf-8")
    return epub_out, chapters