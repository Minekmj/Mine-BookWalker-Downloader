from typing import Dict

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class ExtraPromptsPanel(QWidget):
    changed = Signal()

    PROMPT_PARTS = [
        ("prompt_extra_ocr", "OCR 전사 (1차 텍스트 추출)", "예: 특정 고유명사 표기 유지, 특정 기호를 <bic>로 처리 등"),
        ("prompt_extra_content_review", "최종 내용 검수 (오인식·문단 교정)", "예: 말투·문장부호 유지, 특정 단어 교정 기준 등"),
        ("prompt_extra_toc_reconcile", "목차·구분자 판별 및 상호 교정", "예: '제○절'은 구분자(<bic>)로만 처리, 특정 제목만 장으로 분리 등"),
        ("prompt_extra_illust_toc", "삽화 이미지 목차·장 표지 판별", "예: 일러스트 위 장 제목 스타일이나 예외 규칙 안내"),
        ("prompt_extra_missing_toc", "누락 목차 구간 탐색", "예: 본문 중간 장 시작 패턴이나 특수 장 제목 형태 안내"),
        ("prompt_extra_structure_audit", "최종 구조·삽화 감사", "예: 최종 목차 등록/제외 기준이나 특수 구성 안내"),
    ]

    def __init__(self, initial_settings: Dict, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.editors = {}
        for key, title, placeholder in self.PROMPT_PARTS:
            box = QGroupBox(title)
            v = QVBoxLayout(box)
            v.setContentsMargins(10, 14, 10, 10)
            edit = QPlainTextEdit()
            edit.setFixedHeight(68)
            edit.setPlaceholderText(placeholder)
            edit.textChanged.connect(lambda *_: self.changed.emit())
            self.editors[key] = edit
            v.addWidget(edit)
            layout.addWidget(box)

        layout.addStretch(1)
        scroll.setWidget(content)
        self.set_config(initial_settings)

    def get_config(self) -> Dict:
        return {key: edit.toPlainText().strip() for key, edit in self.editors.items()}

    def set_config(self, cfg: Dict):
        for key, edit in self.editors.items():
            edit.blockSignals(True)
            edit.setPlainText(str(cfg.get(key, "") or ""))
            edit.blockSignals(False)
