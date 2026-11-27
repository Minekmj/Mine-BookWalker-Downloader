import hashlib
from pathlib import Path
import shutil
from typing import List

from PySide6.QtCore import QTimer

from core.config.paths import SESSION_TMP
from core.vision.image_utils import (
    crop_normalized_rect,
    image_fingerprint,
    is_blank_image,
    load_image_rgb,
    save_tmp_image,
)
from core.vision.novel_detector import SplitPart
from core.vision.page_pipeline import compute_base_parts, split_illustration_side_crop
from ui.workers.analysis_worker import PageAnalysisWorker


class PreviewCacheMixin:
    def _preview_cache_root(self) -> Path:
        return SESSION_TMP / "preview"

    def _preview_cache_dir(self, params_key: str) -> Path:
        digest = hashlib.sha1(params_key.encode("utf-8")).hexdigest()[:12]
        cache_dir = self._preview_cache_root() / digest
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _cleanup_preview_cache(self, keep_dir: Path = None):
        root = self._preview_cache_root()
        if not root.is_dir():
            return
        for child in root.iterdir():
            if keep_dir is not None and child == keep_dir:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    @staticmethod
    def _part_image(part: SplitPart):
        if part.image is not None:
            return part.image
        if part.image_path is not None and Path(part.image_path).is_file():
            return load_image_rgb(Path(part.image_path))
        return None

    def _part_is_blank(self, part: SplitPart) -> bool:
        if part.is_blank is not None:
            return bool(part.is_blank)
        img = self._part_image(part)
        if img is None:
            return True
        blank = is_blank_image(img)
        part.is_blank = blank
        return blank

    def _base_parts(self, file_idx: int) -> List[SplitPart]:
        params_key = self._params_key()
        cache_dir = self._preview_cache_dir(params_key)
        if not hasattr(self, "_analysis_cache") or self._analysis_cache_key != params_key:
            self._analysis_cache = {}
            self._analysis_cache_key = params_key
            self._cleanup_preview_cache(keep_dir=cache_dir)
        if file_idx in self._analysis_cache:
            return self._analysis_cache[file_idx]
        path = self._preview_files[file_idx]
        img = load_image_rgb(path)
        is_novel = self._is_novel()
        if not is_novel and file_idx == 0 and self.chk_cover_crop.isChecked() and self._cover_crop_rect:
            cropped = crop_normalized_rect(img, self._cover_crop_rect)
            parts = [SplitPart(cropped, "첫 장 표지 영역 자르기", True, "사용자 지정 표지 영역")]
        else:
            params = self._analysis_params()
            params["auto_separate_disabled"] = bool(self._no_auto_separate.get(path.name, False))
            parts = compute_base_parts(img, file_idx == 0, is_novel, params)
        cached_parts = []
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
        self._analysis_cache[file_idx] = cached_parts
        return cached_parts

    def _restart_analysis(self):
        if not self._preview_files or not self._is_novel():
            return
        old = getattr(self, "_analysis_worker", None)
        if old is not None:
            try:
                old.cancel()
            except RuntimeError:
                pass
            self._analysis_worker = None
        params_key = self._params_key()
        cache_dir = self._preview_cache_dir(params_key)
        self._analysis_cache = {}
        self._analysis_cache_key = params_key
        self._cleanup_preview_cache(keep_dir=cache_dir)
        worker = PageAnalysisWorker(
            self._preview_files,
            self._analysis_params(),
            True,
            self._cur_file_idx,
            self,
            cache_dir=cache_dir,
        )
        worker.page_ready.connect(self._on_page_analyzed)
        worker.finished.connect(lambda w=worker: self._on_analysis_worker_finished(w))
        worker.finished.connect(worker.deleteLater)
        self._analysis_worker = worker
        worker.start()

    def _on_analysis_worker_finished(self, worker):
        if getattr(self, "_analysis_worker", None) is worker:
            self._analysis_worker = None

    def _schedule_analysis(self):
        if not hasattr(self, "_analysis_timer"):
            self._analysis_timer = QTimer(self)
            self._analysis_timer.setSingleShot(True)
            self._analysis_timer.timeout.connect(self._restart_analysis)
        self._analysis_timer.start(250)

    def _on_page_analyzed(self, index: int, parts):
        if getattr(self, "_analysis_cache_key", None) != self._params_key():
            return
        self._analysis_cache[index] = parts
        if index == self._cur_file_idx:
            self._refresh_preview()

    def _resolve_file_parts(self, file_idx: int) -> List[SplitPart]:
        parts = self._base_parts(file_idx)
        overrides = []
        for part_index, part in enumerate(parts):
            key = self._classification_key(file_idx, part_index, part)
            if key in self._classification_overrides:
                value = bool(self._classification_overrides[key])
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
        fname = self._preview_files[file_idx].name
        if self._is_novel() and not self.chk_split_large.isChecked() and not self._illust_no_merge.get(fname, False) and len(overrides) > 1:
            non_blank = [p for p in overrides if not self._part_is_blank(p)]
            if len(non_blank) >= 2 and all(p.is_illustration for p in non_blank):
                raw_img = load_image_rgb(self._preview_files[file_idx])
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
                merged_key = self._classification_key(file_idx, 0, merged)
                if merged_key in self._classification_overrides:
                    val = bool(self._classification_overrides[merged_key])
                    merged.is_illustration = val
                    merged.analysis_reason = "사용자 지정 삽화" if val else "사용자 지정 본문"
                return self._apply_side_crops_to_parts(file_idx, [merged])
        return self._apply_side_crops_to_parts(file_idx, overrides)

    def _apply_side_crops_to_parts(self, file_idx: int, parts: List[SplitPart]) -> List[SplitPart]:
        if not self._is_novel():
            return parts
        if getattr(self, "_side_crop_editing", False) and file_idx == self._cur_file_idx:
            return parts
        r_params = self._render_params()
        expanded: List[SplitPart] = []
        for idx, part in enumerate(parts):
            key = self._classification_key(file_idx, idx, part)
            sc = self._illust_side_crops.get(key)
            if part.is_illustration and sc and len(sc) == 2 and (float(sc[0]) > 0.0 or float(sc[1]) > 0.0):
                part_img = self._part_image(part)
                if part_img is not None and not self._part_is_blank(part):
                    src_part = SplitPart(
                        part_img,
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
