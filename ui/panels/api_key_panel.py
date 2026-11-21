from typing import Dict

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from ui.panels.api_key_list import ApiKeyListWidget


class ApiKeyPanel(QWidget):

    def __init__(self, initial_settings: Dict, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        box = QGroupBox("Gemini API 키")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(16, 22, 16, 16)
        self.key_list = ApiKeyListWidget()
        box_layout.addWidget(self.key_list)
        root.addWidget(box)
        root.addStretch()

        self.set_config(initial_settings)

    def get_config(self) -> Dict:
        return {"gemini_api_keys": self.key_list.get_text()}

    def set_config(self, cfg: Dict):
        self.key_list.set_text(str(cfg.get("gemini_api_keys", "")))
