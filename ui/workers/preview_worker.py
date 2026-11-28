from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from core.vision.image_utils import (
    crop_normalized_rect,
    detect_illustration_bounds,
    image_fingerprint,
    is_blank_image,
    list_images_in_folder,
    load_image_rgb,
    save_tmp_image,
)
from core.vision.mode_detector import detect_folder_mode
from core.vision.novel_detector import SplitPart
from core.vision.page_pipeline import (
    compute_base_parts,
    default_illust_trim_enabled,
    render_illustration_image,
    split_illustration_side_crop,
)


def pil_to_qimage(img: Optional[Image.Image]) -> Optional[QImage]:
    if img is None:
        return None
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return qimg.copy()


def part_image(part: SplitPart) -> Optional[Image.Image]:
    if part.image is not None:
        return part.image
    if part.image_path is not None and Path(part.image_path).is_file():
        return load_image_rgb(Path(part.image_path))
    return None


def part_is_blank(part: SplitPart) -> bool:
    if part.is_blank is not None:
        return bool(part.is_blank)
    img = part_image(part)
    if img is None:
        return True
    blank = is_blank_image(img)
    part.is_blank = blank
    return blank


def classification_key_for_part(filename: str, part_idx: int, part: SplitPart) -> str:
    fp = part.fingerprint
    if not fp:
        img = part_image(part)
        fp = image_fingerprint(img) if img is not None else ""
        part.fingerprint = fp
    return f"{filename}::{part_idx}::{fp}"


def compute_and_cache_base_parts(
    file_path: Path,
    file_idx: int,
    is_novel: bool,
    analysis_params: Dict,
    cache_dir: Path,
    cover_crop_enabled: bool = False,
    cover_crop_rect: Optional[Tuple[float, float, float, float]] = None,
    no_auto_separate: Optional[Dict] = None,
) -> List[SplitPart]:
    img = load_image_rgb(file_path)
    if not is_novel and file_idx == 0 and cover_crop_enabled and cover_crop_rect:
        cropped = crop_normalized_rect(img, cover_crop_rect)
        parts = [SplitPart(cropped, "첫 장 표지 영역 자르기", True, "사용자 지정 표지 영역")]
    else:
        params = dict(analysis_params)
        params["auto_separate_disabled"] = bool((no_auto_separate or {}).get(file_path.name, False))
        parts = compute_base_parts(img, file_idx == 0, is_novel, params)

    cached_parts: List[SplitPart] = []
    for part_idx, part in enumerate(parts):
        fp = part.fingerprint or image_fingerprint(part.image)
        blank = part.is_blank if part.is_blank is not None else is_blank_image(part.image)
        out_path = cache_dir / f"{file_idx:05d}_{part_idx:02d}.png"
        save_tmp_image(part.image, out_path)
        cached_parts.append(
            SplitPart(
                None,
                part.split_note,
                part.is_illustration,
                part.analysis_reason,
                header_cut_applied=part.header_cut_applied,
                detected_header_cut_y=part.detected_header_cut_y,
                is_mini_illust=part.is_mini_illust,
                image_path=out_path,
                fingerprint=fp,
                is_blank=blank,
            )
        )
    return cached_parts


def _apply_side_crops(
    file_path: Path,
    file_idx: int,
    parts: List[SplitPart],
    is_novel: bool,
    illust_side_crops: Dict,
    side_crop_editing: bool,
    cur_file_idx: int,
) -> List[SplitPart]:
    if not is_novel:
        return parts
    if side_crop_editing and file_idx == cur_file_idx:
        return parts
    fname = file_path.name
    expanded: List[SplitPart] = []
    for idx, part in enumerate(parts):
        key = classification_key_for_part(fname, idx, part)
        sc = illust_side_crops.get(key)
        if part.is_illustration and sc and len(sc) == 2 and (float(sc[0]) > 0.0 or float(sc[1]) > 0.0):
            p_img = part_image(part)
            if p_img is not None and not part_is_blank(part):
                src_part = SplitPart(
                    p_img,
                    part.split_note,
                    part.is_illustration,
                    part.analysis_reason,
                    header_cut_applied=part.header_cut_applied,
                    detected_header_cut_y=part.detected_header_cut_y,
                    is_mini_illust=part.is_mini_illust,
                )
                split_parts = split_illustration_side_crop(
                    src_part,
                    side_crop=(float(sc[0]), float(sc[1])),
                    origin_key=key,
                )
                for sp in split_parts:
                    sp.fingerprint = image_fingerprint(sp.image)
                    sp.is_blank = is_blank_image(sp.image)
                expanded.extend(split_parts)
                continue
        expanded.append(part)
    return expanded


def resolve_parts_for_file(
    base_parts: List[SplitPart],
    file_path: Path,
    file_idx: int,
    is_novel: bool,
    split_large_images: bool,
    classification_overrides: Dict,
    illust_no_merge: Dict,
    illust_side_crops: Dict,
    side_crop_editing: bool = False,
    cur_file_idx: int = -1,
) -> List[SplitPart]:
    fname = file_path.name
    overrides: List[SplitPart] = []
    for part_index, part in enumerate(base_parts):
        key = classification_key_for_part(fname, part_index, part)
        if key in classification_overrides:
            value = bool(classification_overrides[key])
            part = SplitPart(
                part.image,
                part.split_note,
                value,
                "사용자 지정 삽화" if value else "사용자 지정 본문",
                header_cut_applied=part.header_cut_applied,
                detected_header_cut_y=part.detected_header_cut_y,
                is_mini_illust=part.is_mini_illust,
                image_path=part.image_path,
                fingerprint=part.fingerprint,
                is_blank=part.is_blank,
            )
        overrides.append(part)

    if is_novel and not split_large_images and not illust_no_merge.get(fname, False) and len(overrides) > 1:
        non_blank = [p for p in overrides if not part_is_blank(p)]
        if len(non_blank) >= 2 and all(p.is_illustration for p in non_blank):
            raw_img = load_image_rgb(file_path)
            fp = image_fingerprint(raw_img)
            blank = is_blank_image(raw_img)
            merged = SplitPart(
                raw_img,
                "양면 삽화 병합",
                True,
                "분리된 양면 삽화 자동 병합",
                header_cut_applied=False,
                fingerprint=fp,
                is_blank=blank,
            )
            merged_key = classification_key_for_part(fname, 0, merged)
            if merged_key in classification_overrides:
                val = bool(classification_overrides[merged_key])
                merged.is_illustration = val
                merged.analysis_reason = "사용자 지정 삽화" if val else "사용자 지정 본문"
            return _apply_side_crops(
                file_path,
                file_idx,
                [merged],
                is_novel,
                illust_side_crops,
                side_crop_editing,
                cur_file_idx,
            )

    return _apply_side_crops(
        file_path,
        file_idx,
        overrides,
        is_novel,
        illust_side_crops,
        side_crop_editing,
        cur_file_idx,
    )


class PreviewRenderWorker(QThread):
    rendered = Signal(int, dict)

    def __init__(self, request_id: int, snapshot: Dict, parent=None):
        super().__init__(parent)
        self._request_id = request_id
        self._snapshot = snapshot
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        s = self._snapshot
        file_idx: int = s["file_idx"]
        sub_idx: int = s["sub_idx"]
        file_path: Path = s["file_path"]
        is_novel: bool = s["is_novel"]
        params_key: str = s["params_key"]
        cache_dir: Path = s["cache_dir"]

        base_parts = s["cached_base_parts"]
        newly_computed_base: Optional[List[SplitPart]] = None
        if base_parts is None:
            base_parts = compute_and_cache_base_parts(
                file_path=file_path,
                file_idx=file_idx,
                is_novel=is_novel,
                analysis_params=s["analysis_params"],
                cache_dir=cache_dir,
                cover_crop_enabled=s["cover_crop_enabled"],
                cover_crop_rect=s["cover_crop_rect"],
                no_auto_separate=s["no_auto_separate"],
            )
            newly_computed_base = base_parts

        if self._cancelled:
            return

        resolved_parts = resolve_parts_for_file(
            base_parts=base_parts,
            file_path=file_path,
            file_idx=file_idx,
            is_novel=is_novel,
            split_large_images=s["split_large_images"],
            classification_overrides=s["classification_overrides"],
            illust_no_merge=s["illust_no_merge"],
            illust_side_crops=s["illust_side_crops"],
            side_crop_editing=s["side_crop_editing"],
            cur_file_idx=file_idx,
        )
        if self._cancelled:
            return

        if sub_idx < 0:
            sub_idx = max(0, len(resolved_parts) - 1)
        else:
            sub_idx = max(0, min(sub_idx, len(resolved_parts) - 1))

        part = resolved_parts[sub_idx]
        p_img = part_image(part)
        if self._cancelled:
            return

        is_blank = True if p_img is None else part_is_blank(part)
        if self._cancelled:
            return

        display_qimg: Optional[QImage] = None
        edit_qimg: Optional[QImage] = None
        trim_this = False

        if p_img is None or is_blank:
            display_qimg = pil_to_qimage(p_img)
        elif not is_novel:
            display_qimg = pil_to_qimage(p_img)
        elif part.is_illustration:
            r_params = s["render_params"]
            key = classification_key_for_part(file_path.name, sub_idx, part)
            trim_overrides = s["illust_trim_overrides"]
            if key in trim_overrides:
                trim_this = bool(trim_overrides[key])
            else:
                trim_this = default_illust_trim_enabled(part, {"trim_enabled": r_params["trim_enabled"]})

            if s["side_crop_editing"]:
                display_qimg = pil_to_qimage(p_img)
            else:
                render_part = SplitPart(
                    p_img,
                    part.split_note,
                    part.is_illustration,
                    part.analysis_reason,
                    header_cut_applied=part.header_cut_applied,
                    detected_header_cut_y=part.detected_header_cut_y,
                    is_mini_illust=part.is_mini_illust,
                )
                display_img = render_illustration_image(
                    render_part,
                    r_params,
                    trim_override=trim_this,
                    side_crop=None,
                )
                if self._cancelled:
                    return
                display_qimg = pil_to_qimage(display_img)
                edit_qimg = pil_to_qimage(p_img)
        else:
            display_qimg = pil_to_qimage(p_img)

        if self._cancelled:
            return

        # Strip in-memory PIL images from resolved_parts if they already have image_path,
        # or keep them lightweight (note: merged/side-cropped parts may only have in-memory image).
        self.rendered.emit(
            self._request_id,
            {
                "file_idx": file_idx,
                "sub_idx": sub_idx,
                "params_key": params_key,
                "base_parts": newly_computed_base,
                "resolved_parts": resolved_parts,
                "is_blank": is_blank,
                "trim_this": trim_this,
                "display_qimg": display_qimg,
                "edit_qimg": edit_qimg,
            },
        )


class PreviewSearchWorker(QThread):
    page_analyzed = Signal(int, object, str)
    found = Signal(int, int, int)
    not_found = Signal(int)

    def __init__(
        self,
        request_id: int,
        files: List[Path],
        start_file: int,
        start_part: int,
        target_is_illustration: bool,
        snapshot: Dict,
        parent=None,
    ):
        super().__init__(parent)
        self._request_id = request_id
        self._files = list(files)
        self._start_file = start_file
        self._start_part = start_part
        self._target_is_illustration = bool(target_is_illustration)
        self._snapshot = snapshot
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        total = len(self._files)
        if total == 0:
            self.not_found.emit(self._request_id)
            return

        s = self._snapshot
        cached_map: Dict[int, List[SplitPart]] = s["cached_base_map"]
        params_key: str = s["params_key"]
        cache_dir: Path = s["cache_dir"]
        is_novel: bool = s["is_novel"]

        for file_offset in range(total):
            if self._cancelled:
                return
            file_index = (self._start_file + file_offset) % total
            file_path = self._files[file_index]
            base_parts = cached_map.get(file_index)
            if base_parts is None:
                base_parts = compute_and_cache_base_parts(
                    file_path=file_path,
                    file_idx=file_index,
                    is_novel=is_novel,
                    analysis_params=s["analysis_params"],
                    cache_dir=cache_dir,
                    cover_crop_enabled=s["cover_crop_enabled"],
                    cover_crop_rect=s["cover_crop_rect"],
                    no_auto_separate=s["no_auto_separate"],
                )
                if self._cancelled:
                    return
                self.page_analyzed.emit(file_index, base_parts, params_key)

            parts = resolve_parts_for_file(
                base_parts=base_parts,
                file_path=file_path,
                file_idx=file_index,
                is_novel=is_novel,
                split_large_images=s["split_large_images"],
                classification_overrides=s["classification_overrides"],
                illust_no_merge=s["illust_no_merge"],
                illust_side_crops=s["illust_side_crops"],
                side_crop_editing=False,
                cur_file_idx=-1,
            )
            start_sub = (self._start_part + 1) if file_offset == 0 else 0
            for part_index in range(start_sub, len(parts)):
                if self._cancelled:
                    return
                part = parts[part_index]
                if not part_is_blank(part) and (bool(part.is_illustration) == self._target_is_illustration):
                    self.found.emit(self._request_id, file_index, part_index)
                    return

        if not self._cancelled:
            self.not_found.emit(self._request_id)


class FolderModeWorker(QThread):
    completed = Signal(int, str, object, str)

    def __init__(self, request_id: int, folder: Path, sensitivity: str, parent=None):
        super().__init__(parent)
        self._request_id = request_id
        self._folder = folder
        self._sensitivity = sensitivity
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        files = list_images_in_folder(self._folder)
        if self._cancelled:
            return
        mode = "novel"
        if files:
            mode, _, _, _ = detect_folder_mode(files, self._sensitivity)
        if not self._cancelled:
            self.completed.emit(self._request_id, str(self._folder), files, mode)


class CoverCropWorker(QThread):
    completed = Signal(int, str, object, object)

    def __init__(self, request_id: int, action_mode: str, file_path: Path, parent=None):
        super().__init__(parent)
        self._request_id = request_id
        self._action_mode = action_mode
        self._file_path = file_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        image = load_image_rgb(self._file_path)
        if self._cancelled:
            return
        bounds = None
        if self._action_mode == "auto":
            bounds = detect_illustration_bounds(image, padding_ratio=0.0)
        if not self._cancelled:
            self.completed.emit(self._request_id, self._action_mode, image, bounds)
