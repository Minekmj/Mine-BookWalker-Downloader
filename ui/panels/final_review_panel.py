from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class FinalReviewPanel(QWidget):
    changed = Signal()

    REVIEW_CHECKS = [
        ("gemini_review_ocr", "OCR 오인식·누락 문장 교정"),
        ("gemini_review_paragraphs", "문단 분리·문장 연결·읽기 흐름 검수"),
        ("gemini_review_headings", "장 제목·소제목 분류 검수"),
        ("gemini_review_toc", "인쇄 목차와 실제 장 제목 대조"),
        ("gemini_review_illust_toc", "삽화 이미지에서 목차·장 표지 후보 판별"),
        ("epub_register_dividers_in_toc", "구분자(1, 2, 3...)를 EPUB 목차(내비게이션)에 등록"),
        ("gemini_review_duplicates", "중복 문단·페이지 내용 검수"),
        ("gemini_review_illustrations", "삽화 순서·누락·크롭 상태 검수"),
    ]

    def __init__(self, initial_settings: Dict, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        self.chk_final_review = QCheckBox("최종 검수 실행 및 수정 결과 반영")
        self.chk_final_review.setStyleSheet("font-weight: 600;")
        root.addWidget(self.chk_final_review)

        self.check_widgets = {}
        for key, label in self.REVIEW_CHECKS:
            box = QCheckBox(label)
            self.check_widgets[key] = box
            root.addWidget(box)

        batch_grid = QGridLayout()
        batch_grid.setSpacing(10)

        self.spin_review_passes = QSpinBox()
        self.spin_review_passes.setRange(1, 3)
        self.spin_review_passes.setSuffix("회")
        self.spin_review_passes.setMinimumHeight(30)

        self.spin_review_batch = QSpinBox()
        self.spin_review_batch.setRange(1, 30)
        self.spin_review_batch.setSuffix("장")
        self.spin_review_batch.setMinimumHeight(30)

        self.spin_illust_toc_batch = QSpinBox()
        self.spin_illust_toc_batch.setRange(1, 20)
        self.spin_illust_toc_batch.setSuffix("장")
        self.spin_illust_toc_batch.setMinimumHeight(30)

        self.spin_missing_toc_batch = QSpinBox()
        self.spin_missing_toc_batch.setRange(1, 20)
        self.spin_missing_toc_batch.setSuffix("장")
        self.spin_missing_toc_batch.setMinimumHeight(30)

        batch_grid.addWidget(QLabel("수정·재검수 반복"), 0, 0)
        batch_grid.addWidget(self.spin_review_passes, 0, 1)
        batch_grid.addWidget(QLabel("내용 검수 배치"), 0, 2)
        batch_grid.addWidget(self.spin_review_batch, 0, 3)
        batch_grid.addWidget(QLabel("삽화 목차 배치"), 1, 0)
        batch_grid.addWidget(self.spin_illust_toc_batch, 1, 1)
        batch_grid.addWidget(QLabel("누락 목차 배치"), 1, 2)
        batch_grid.addWidget(self.spin_missing_toc_batch, 1, 3)
        batch_grid.setColumnStretch(4, 1)
        root.addLayout(batch_grid)
        root.addStretch()

        self.chk_final_review.toggled.connect(self._sync_enabled)
        self.chk_final_review.toggled.connect(lambda *_: self.changed.emit())
        for box in self.check_widgets.values():
            box.toggled.connect(lambda *_: self.changed.emit())
        for spin in (self.spin_review_passes, self.spin_review_batch, self.spin_illust_toc_batch, self.spin_missing_toc_batch):
            spin.valueChanged.connect(lambda *_: self.changed.emit())

        self.set_config(initial_settings)

    def _sync_enabled(self, enabled: bool):
        for box in self.check_widgets.values():
            box.setEnabled(enabled)
        for spin in (self.spin_review_passes, self.spin_review_batch, self.spin_illust_toc_batch, self.spin_missing_toc_batch):
            spin.setEnabled(enabled)

    def get_config(self) -> Dict:
        config = {"gemini_final_review": self.chk_final_review.isChecked()}
        for key, box in self.check_widgets.items():
            config[key] = box.isChecked()
        config["gemini_review_passes"] = self.spin_review_passes.value()
        config["gemini_review_batch_size"] = self.spin_review_batch.value()
        config["gemini_illust_toc_batch_size"] = self.spin_illust_toc_batch.value()
        config["gemini_missing_toc_batch_size"] = self.spin_missing_toc_batch.value()
        return config

    def set_config(self, cfg: Dict):
        self.chk_final_review.blockSignals(True)
        self.chk_final_review.setChecked(bool(cfg.get("gemini_final_review", True)))
        self.chk_final_review.blockSignals(False)
        for key, box in self.check_widgets.items():
            box.blockSignals(True)
            default_val = False if key == "epub_register_dividers_in_toc" else True
            box.setChecked(bool(cfg.get(key, default_val)))
            box.blockSignals(False)
        for spin, key, default in (
            (self.spin_review_passes, "gemini_review_passes", 2),
            (self.spin_review_batch, "gemini_review_batch_size", 15),
            (self.spin_illust_toc_batch, "gemini_illust_toc_batch_size", 5),
            (self.spin_missing_toc_batch, "gemini_missing_toc_batch_size", 8),
        ):
            spin.blockSignals(True)
            spin.setValue(int(cfg.get(key, default)))
            spin.blockSignals(False)
        self._sync_enabled(self.chk_final_review.isChecked())
