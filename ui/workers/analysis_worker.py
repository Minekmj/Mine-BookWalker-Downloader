from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from core.vision.image_utils import image_fingerprint, is_blank_image, load_image_rgb, save_tmp_image
from core.vision.novel_detector import SplitPart
from core.vision.page_pipeline import compute_base_parts


class PageAnalysisWorker(QThread):
    page_ready = Signal(int, object)

    def __init__(
        self,
        files: List,
        params: dict,
        is_novel: bool,
        start_index: int = 0,
        parent=None,
        max_workers: int = 4,
        cache_dir: Optional[Path] = None,
    ):
        super().__init__(parent)
        self._files = list(files)
        self._params = dict(params)
        self._is_novel = is_novel
        self._start = max(0, min(start_index, len(self._files) - 1)) if self._files else 0
        self._max_workers = max(1, min(8, int(max_workers)))
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _analyze_one(self, index: int):
        if self._cancelled:
            return index, None
        image = load_image_rgb(self._files[index])
        if self._cancelled:
            return index, None
        parts = compute_base_parts(image, index == 0, self._is_novel, self._params)
        if self._cache_dir is None:
            return index, parts
        cached_parts = []
        for part_idx, part in enumerate(parts):
            if self._cancelled:
                return index, None
            fp = part.fingerprint or image_fingerprint(part.image)
            blank = part.is_blank if part.is_blank is not None else is_blank_image(part.image)
            out_path = self._cache_dir / f"{index:05d}_{part_idx:02d}.png"
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
        return index, cached_parts

    def run(self):
        total = len(self._files)
        if total == 0:
            return
        idx0, parts0 = self._analyze_one(self._start)
        if self._cancelled:
            return
        if parts0 is not None:
            self.page_ready.emit(idx0, parts0)
        rest = list(range(self._start + 1, total)) + list(range(0, self._start))
        if not rest:
            return
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = [executor.submit(self._analyze_one, index) for index in rest]
            for future in as_completed(futures):
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                index, parts = future.result()
                if self._cancelled:
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                if parts is not None:
                    self.page_ready.emit(index, parts)