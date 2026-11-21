from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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

        pass_row = QHBoxLayout()
        pass_row.addWidget(QLabel("수정·재검수 반복"))
        self.spin_review_passes = QSpinBox()
        self.spin_review_passes.setRange(1, 3)
        self.spin_review_passes.setSuffix("회")
        self.spin_review_passes.setMinimumHeight(30)
        pass_row.addWidget(self.spin_review_passes)
        pass_row.addStretch()
        root.addLayout(pass_row)
        root.addStretch()

        self.chk_final_review.toggled.connect(self._sync_enabled)
        self.chk_final_review.toggled.connect(lambda *_: self.changed.emit())
        for box in self.check_widgets.values():
            box.toggled.connect(lambda *_: self.changed.emit())
        self.spin_review_passes.valueChanged.connect(lambda *_: self.changed.emit())

        self.set_config(initial_settings)

    def _sync_enabled(self, enabled: bool):
        for box in self.check_widgets.values():
            box.setEnabled(enabled)
        self.spin_review_passes.setEnabled(enabled)

    def get_config(self) -> Dict:
        config = {"gemini_final_review": self.chk_final_review.isChecked()}
        for key, box in self.check_widgets.items():
            config[key] = box.isChecked()
        config["gemini_review_passes"] = self.spin_review_passes.value()
        return config

    def set_config(self, cfg: Dict):
        self.chk_final_review.blockSignals(True)
        self.chk_final_review.setChecked(bool(cfg.get("gemini_final_review", True)))
        self.chk_final_review.blockSignals(False)
        for key, box in self.check_widgets.items():
            box.blockSignals(True)
            box.setChecked(bool(cfg.get(key, True)))
            box.blockSignals(False)
        self.spin_review_passes.blockSignals(True)
        self.spin_review_passes.setValue(int(cfg.get("gemini_review_passes", 2)))
        self.spin_review_passes.blockSignals(False)
        self._sync_enabled(self.chk_final_review.isChecked())
