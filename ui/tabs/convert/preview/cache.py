import hashlib
from pathlib import Path
import shutil
from typing import Dict, List, Optional

from PySide6.QtCore import QTimer
from shiboken6 import isValid

from core.config.paths import SESSION_TMP
from core.vision.novel_detector import SplitPart
from ui.workers.analysis_worker import PageAnalysisWorker
from ui.workers.preview_worker import (
    PreviewRenderWorker,
    PreviewSearchWorker,
    part_image,
    part_is_blank,
)


class PreviewCacheMixin:
    def _preview_cache_root(self) -> Path:
        return SESSION_TMP / "preview"

    def _preview_cache_dir(self, params_key: str) -> Path:
        digest = hashlib.sha1(params_key.encode("utf-8")).hexdigest()[:12]
        cache_dir = self._preview_cache_root() / digest
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def _cleanup_preview_cache(self, keep_dir: Optional[Path] = None):
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
        return part_image(part)

    def _part_is_blank(self, part: SplitPart) -> bool:
        return part_is_blank(part)

    def _ensure_analysis_cache(self, params_key: str) -> Path:
        cache_dir = self._preview_cache_dir(params_key)
        if not hasattr(self, "_analysis_cache") or getattr(self, "_analysis_cache_key", None) != params_key:
            self._analysis_cache = {}
            self._analysis_cache_key = params_key
            self._cleanup_preview_cache(keep_dir=cache_dir)
        return cache_dir

    def _track_bg_worker(self, worker):
        if not hasattr(self, "_bg_workers"):
            self._bg_workers = set()
        self._bg_workers.add(worker)
        worker.finished.connect(lambda w=worker: self._untrack_bg_worker(w))
        worker.finished.connect(worker.deleteLater)

    def _untrack_bg_worker(self, worker):
        if hasattr(self, "_bg_workers"):
            self._bg_workers.discard(worker)
        if getattr(self, "_preview_worker", None) is worker:
            self._preview_worker = None
        if getattr(self, "_preview_search_worker", None) is worker:
            self._preview_search_worker = None
        if getattr(self, "_folder_mode_worker", None) is worker:
            self._folder_mode_worker = None
        if getattr(self, "_cover_crop_worker", None) is worker:
            self._cover_crop_worker = None

    def _cancel_worker_attr(self, attr_name: str):
        old = getattr(self, attr_name, None)
        if old is not None:
            try:
                if isValid(old):
                    old.cancel()
            except RuntimeError:
                pass
            setattr(self, attr_name, None)

    def shutdown_preview_workers(self):
        for timer_attr in ("_analysis_timer", "_preview_render_timer"):
            timer = getattr(self, timer_attr, None)
            if timer is not None:
                try:
                    timer.stop()
                except RuntimeError:
                    pass
        for attr in ("_analysis_worker", "_preview_worker", "_preview_search_worker", "_folder_mode_worker", "_cover_crop_worker"):
            self._cancel_worker_attr(attr)
        for worker in list(getattr(self, "_bg_workers", ())):
            try:
                if isValid(worker):
                    worker.cancel()
                    worker.wait(500)
            except RuntimeError:
                pass

    def _build_preview_snapshot(self, file_idx: int, sub_idx: int) -> Dict:
        params_key = self._params_key()
        cache_dir = self._ensure_analysis_cache(params_key)
        return {
            "file_idx": file_idx,
            "sub_idx": sub_idx,
            "file_path": self._preview_files[file_idx],
            "is_novel": self._is_novel(),
            "params_key": params_key,
            "cache_dir": cache_dir,
            "cached_base_parts": self._analysis_cache.get(file_idx),
            "analysis_params": self._analysis_params(),
            "render_params": self._render_params(),
            "split_large_images": self.chk_split_large.isChecked(),
            "cover_crop_enabled": self.chk_cover_crop.isChecked(),
            "cover_crop_rect": self._cover_crop_rect,
            "classification_overrides": dict(self._classification_overrides),
            "illust_trim_overrides": dict(self._illust_trim_overrides),
            "illust_side_crops": dict(self._illust_side_crops),
            "illust_no_merge": dict(self._illust_no_merge),
            "no_auto_separate": dict(self._no_auto_separate),
            "side_crop_editing": bool(self._side_crop_editing),
        }

    def _schedule_preview_render(self, file_idx: int, sub_idx: int):
        self._preview_req_id = getattr(self, "_preview_req_id", 0) + 1
        self._cancel_worker_attr("_preview_worker")
        self._pending_preview_req = (self._preview_req_id, self._build_preview_snapshot(file_idx, sub_idx))
        if not hasattr(self, "_preview_render_timer"):
            self._preview_render_timer = QTimer(self)
            self._preview_render_timer.setSingleShot(True)
            self._preview_render_timer.timeout.connect(self._start_preview_render)
        self._preview_render_timer.start(20)

    def _start_preview_render(self):
        pending = getattr(self, "_pending_preview_req", None)
        if not pending:
            return
        req_id, snapshot = pending
        if req_id != getattr(self, "_preview_req_id", 0):
            return
        worker = PreviewRenderWorker(req_id, snapshot, self)
        worker.rendered.connect(self._on_preview_rendered)
        self._track_bg_worker(worker)
        self._preview_worker = worker
        worker.start()

    def _start_preview_search(self, target_is_illustration: bool):
        if not self._preview_files:
            return
        self._preview_search_req_id = getattr(self, "_preview_search_req_id", 0) + 1
        req_id = self._preview_search_req_id
        self._cancel_worker_attr("_preview_search_worker")

        params_key = self._params_key()
        cache_dir = self._ensure_analysis_cache(params_key)
        snapshot = {
            "params_key": params_key,
            "cache_dir": cache_dir,
            "cached_base_map": dict(self._analysis_cache),
            "is_novel": self._is_novel(),
            "analysis_params": self._analysis_params(),
            "split_large_images": self.chk_split_large.isChecked(),
            "cover_crop_enabled": self.chk_cover_crop.isChecked(),
            "cover_crop_rect": self._cover_crop_rect,
            "classification_overrides": dict(self._classification_overrides),
            "illust_no_merge": dict(self._illust_no_merge),
            "illust_side_crops": dict(self._illust_side_crops),
            "no_auto_separate": dict(self._no_auto_separate),
        }
        label_text = "다음 삽화 찾는 중…" if target_is_illustration else "본문 텍스트 페이지 찾는 중…"
        self._set_status_label(self.lbl_preview_type, "statusMute", label_text)

        worker = PreviewSearchWorker(
            req_id,
            self._preview_files,
            self._cur_file_idx,
            max(0, self._cur_sub_idx),
            target_is_illustration,
            snapshot,
            self,
        )
        worker.page_analyzed.connect(self._on_search_page_analyzed)
        worker.found.connect(self._on_preview_search_found)
        worker.not_found.connect(self._on_preview_search_not_found)
        self._track_bg_worker(worker)
        self._preview_search_worker = worker
        worker.start()

    def _on_search_page_analyzed(self, index: int, parts, params_key: str):
        if getattr(self, "_analysis_cache_key", None) != params_key:
            return
        if index not in self._analysis_cache:
            self._analysis_cache[index] = parts

    def _restart_analysis(self):
        if not self._preview_files or not self._is_novel():
            return
        self._cancel_worker_attr("_analysis_worker")
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
        already_cached = index in self._analysis_cache
        self._analysis_cache[index] = parts
        if index == self._cur_file_idx and not already_cached:
            self._refresh_preview()
