from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QScrollArea, QSplitter, QVBoxLayout, QWidget

from core.settings import DEFAULT_SETTINGS
from ui.tabs.convert.layout import LayoutMixin
from ui.tabs.convert.preview import PreviewMixin
from ui.tabs.convert.run import RunMixin
from ui.tabs.convert.settings import SettingsMixin


class ConvertTab(LayoutMixin, PreviewMixin, SettingsMixin, RunMixin, QWidget):
    settingsChanged = Signal()

    def __init__(self, initial_settings: Dict, parent=None):
        super().__init__(parent)
        self.worker = None
        self.adv = {**DEFAULT_SETTINGS, **initial_settings}
        self._preview_files: List[Path] = []
        self._cur_file_idx: int = 0
        self._cur_sub_idx: int = 0
        self._classification_overrides = dict(self.adv.get("classification_overrides", {}) or {})
        self._illust_trim_overrides = dict(self.adv.get("illust_trim_overrides", {}) or {})
        saved_crop = self.adv.get("cover_crop_rect")
        self._cover_crop_rect = tuple(saved_crop) if saved_crop and len(saved_crop) == 4 else None

        main_layout = QHBoxLayout(self)
        main_layout.setSpacing(10)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        left_panel = QWidget()
        left = QVBoxLayout(left_panel)
        left.setSpacing(10)
        left.setContentsMargins(0, 0, 6, 0)

        left.addWidget(self._build_path_group())
        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setFrameShape(QFrame.Shape.NoFrame)
        options_scroll.setObjectName("settingsScroll")
        options_scroll.setWidget(self._build_options_group())
        left.addWidget(options_scroll, 1)
        left.addWidget(self._build_run_group())

        right_panel = self._build_preview_group()

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)

        self.apply_settings(self.adv)
        self._on_mode_changed()