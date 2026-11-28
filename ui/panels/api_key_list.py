from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.gemini import parse_api_keys


def mask_key(key: str) -> str:
    if len(key) <= 12:
        return "•" * len(key)
    return f"{key[:6]}…{key[-4:]}"


class ApiKeyChip(QFrame):
    def __init__(self, index: int, key: str, on_remove, parent=None):
        super().__init__(parent)
        self.setObjectName("keyChip")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(8)

        number = QLabel(f"#{index}")
        value = QLabel(mask_key(key))
        value.setStyleSheet("font-family: Consolas, monospace;")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setToolTip(key)

        remove = QPushButton("✕")
        remove.setFixedSize(24, 24)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("이 키 삭제")
        remove.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; border-radius: 4px; color: #6b7280; padding: 0px; min-height: 0px; font-size: 12px; }"
            "QPushButton:hover:enabled { background-color: #fef2f2; color: #b91c1c; }"
        )
        remove.clicked.connect(lambda: on_remove(index - 1))

        row.addWidget(number)
        row.addWidget(value, 1)
        row.addWidget(remove)


class ApiKeyListWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._keys: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        input_row = QHBoxLayout()
        self.edit_input = QLineEdit()
        self.edit_input.setPlaceholderText("API 키 입력 후 Enter (여러 줄 붙여넣기 가능)")
        self.edit_input.setMinimumHeight(30)
        self.edit_input.returnPressed.connect(self._add_from_input)
        self.btn_add = QPushButton("추가")
        self.btn_add.setMinimumHeight(30)
        self.btn_add.clicked.connect(self._add_from_input)
        input_row.addWidget(self.edit_input, 1)
        input_row.addWidget(self.btn_add)
        root.addLayout(input_row)

        self.count_label = QLabel()
        self.count_label.setObjectName("hintLabel")
        root.addWidget(self.count_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFixedHeight(150)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setAutoFillBackground(False)
        self.list_host = QWidget()
        self.list_host.setStyleSheet("background: transparent;")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(6)
        self.list_layout.addStretch()
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._rebuild()

    def keys(self) -> list[str]:
        return list(self._keys)

    def get_text(self) -> str:
        return "\n".join(self._keys)

    def set_text(self, text: str):
        self._keys = parse_api_keys(text)
        self._rebuild()

    def _add_from_input(self):
        added = parse_api_keys(self.edit_input.text())
        self.edit_input.clear()
        if not added:
            return
        for key in added:
            if key not in self._keys:
                self._keys.append(key)
        self._rebuild()

    def _remove(self, index: int):
        if 0 <= index < len(self._keys):
            del self._keys[index]
            self._rebuild()

    def _rebuild(self):
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        for i, key in enumerate(self._keys, start=1):
            chip = ApiKeyChip(i, key, self._remove)
            self.list_layout.insertWidget(self.list_layout.count() - 1, chip)
        self.count_label.setText(f"등록된 키 {len(self._keys)}개 (여러 개면 병렬 실행)" if self._keys else "등록된 키가 없습니다")
        self.list_layout.activate()
        self.list_host.adjustSize()
