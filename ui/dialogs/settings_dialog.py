from typing import Dict

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.panels.epub_design_panel import EpubDesignPanel
from ui.panels.api_key_panel import ApiKeyPanel
from ui.panels.gemini_panel import GeminiPanel
from ui.panels.final_review_panel import FinalReviewPanel
from ui.panels.extra_prompts_panel import ExtraPromptsPanel

class AdvancedSettingsDialog(QDialog):
    def __init__(self, current_settings: Dict, parent=None, initial_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("이미지 to EPUB 설정")
        self.resize(980, 620)
        self.current_settings = dict(current_settings)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        self.tabs = QTabWidget()
        self.api_key_panel = ApiKeyPanel(current_settings)
        self.tabs.addTab(self.api_key_panel, "Gemini 키")
        gemini_page = QWidget()
        gemini_layout = QVBoxLayout(gemini_page)
        self.gemini_panel = GeminiPanel(current_settings, key_source=self.api_key_panel.key_list)
        gemini_layout.addWidget(self.gemini_panel, 1)
        self.tabs.addTab(gemini_page, "Gemini")
        self.tabs.addTab(self._build_split_trim_tab(current_settings), "분할 · 이미지")
        self.tabs.addTab(self._build_epub_tab(current_settings), "EPUB 디자인")
        self.review_panel = FinalReviewPanel(current_settings)
        self.tabs.addTab(self.review_panel, "최종 검수")
        self.extra_prompts_panel = ExtraPromptsPanel(current_settings)
        self.tabs.addTab(self.extra_prompts_panel, "추가 요청사항")
        self.tabs.setCurrentIndex(max(0, min(initial_tab, self.tabs.count() - 1)))
        root.addWidget(self.tabs, 1)
        perf_row = QHBoxLayout()
        perf_row.addWidget(QLabel("이미지 전처리 스레드"))
        self.spin_workers = QSpinBox()
        self.spin_workers.setRange(1, 64)
        self.spin_workers.setValue(int(current_settings.get("parallel_workers", 4)))
        perf_row.addWidget(self.spin_workers)
        perf_row.addStretch()
        root.addLayout(perf_row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("적용")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _build_split_trim_tab(self, settings: Dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        split_group = QGroupBox("페이지 분할")
        split_layout = QVBoxLayout(split_group)
        self.chk_wide_only = QCheckBox("가로가 긴 이미지만 2분할")
        self.chk_wide_only.setChecked(bool(settings.get("split_only_wide", True)))
        split_layout.addWidget(self.chk_wide_only)
        sensitivity_row = QHBoxLayout()
        sensitivity_row.addWidget(QLabel("삽화 판정 민감도"))
        self.combo_illust_sensitivity = QComboBox()
        self.combo_illust_sensitivity.addItem("보수적", "conservative")
        self.combo_illust_sensitivity.addItem("일반", "normal")
        self.combo_illust_sensitivity.addItem("민감", "sensitive")
        sensitivity_idx = self.combo_illust_sensitivity.findData(settings.get("illust_sensitivity", "normal"))
        self.combo_illust_sensitivity.setCurrentIndex(max(0, sensitivity_idx))
        sensitivity_row.addWidget(self.combo_illust_sensitivity)
        sensitivity_row.addStretch()
        split_layout.addLayout(sensitivity_row)
        layout.addWidget(split_group)
        trim_group = QGroupBox("삽화 여백 감지")
        trim_layout = QGridLayout(trim_group)
        side_row = QHBoxLayout()
        self.chk_top = QCheckBox("상단")
        self.chk_bottom = QCheckBox("하단")
        self.chk_left = QCheckBox("왼쪽")
        self.chk_right = QCheckBox("오른쪽")
        self.chk_top.setChecked(bool(settings.get("trim_top", True)))
        self.chk_bottom.setChecked(bool(settings.get("trim_bottom", True)))
        self.chk_left.setChecked(bool(settings.get("trim_left", True)))
        self.chk_right.setChecked(bool(settings.get("trim_right", True)))
        for checkbox in (self.chk_top, self.chk_bottom, self.chk_left, self.chk_right):
            side_row.addWidget(checkbox)
        self.spin_white = QSpinBox()
        self.spin_white.setRange(180, 255)
        self.spin_white.setValue(int(settings.get("white_threshold", 240)))
        self.spin_pad = QSpinBox()
        self.spin_pad.setRange(0, 200)
        self.spin_pad.setValue(int(settings.get("trim_padding", 1)))
        trim_layout.addWidget(QLabel("제거 방향"), 0, 0)
        trim_layout.addLayout(side_row, 0, 1, 1, 3)
        trim_layout.addWidget(QLabel("흰색 판정 기준"), 1, 0)
        trim_layout.addWidget(self.spin_white, 1, 1)
        trim_layout.addWidget(QLabel("여유 픽셀"), 1, 2)
        trim_layout.addWidget(self.spin_pad, 1, 3)
        self.trim_group = trim_group
        self.trim_group.setEnabled(settings.get("mode", "novel") != "manga")
        layout.addWidget(trim_group)
        backup_group = QGroupBox("작업")
        backup_layout = QVBoxLayout(backup_group)
        self.chk_resume = QCheckBox("기존 OCR 백업에서 이어하기")
        self.chk_resume.setChecked(bool(settings.get("resume_from_backup", True)))
        backup_layout.addWidget(self.chk_resume)
        layout.addWidget(backup_group)
        layout.addStretch()
        return widget

    def _build_epub_tab(self, settings: Dict) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        output_group = QGroupBox("출력")
        output_layout = QHBoxLayout(output_group)
        self.chk_make_epub = QCheckBox("EPUB 생성")
        self.chk_make_epub.setChecked(bool(settings.get("make_epub", True)))
        self.chk_save_txt = QCheckBox("TXT와 삽화 폴더 저장")
        self.chk_save_txt.setChecked(bool(settings.get("save_txt_folder", True)))
        output_layout.addWidget(self.chk_make_epub)
        output_layout.addWidget(self.chk_save_txt)
        layout.addWidget(output_group)
        self.epub_design_panel = EpubDesignPanel(settings)
        layout.addWidget(self.epub_design_panel, 1)
        return widget

    def get_values(self) -> Dict:
        values = {
            "parallel_workers": self.spin_workers.value(),
            "split_only_wide": self.chk_wide_only.isChecked(),
            "illust_sensitivity": self.combo_illust_sensitivity.currentData(),
            "trim_top": self.chk_top.isChecked(),
            "trim_bottom": self.chk_bottom.isChecked(),
            "trim_left": self.chk_left.isChecked(),
            "trim_right": self.chk_right.isChecked(),
            "white_threshold": self.spin_white.value(),
            "trim_padding": self.spin_pad.value(),
            "resume_from_backup": self.chk_resume.isChecked(),
            "make_epub": self.chk_make_epub.isChecked(),
            "save_txt_folder": self.chk_save_txt.isChecked(),
        }
        values.update(self.api_key_panel.get_config())
        values.update(self.gemini_panel.get_config())
        values.update(self.epub_design_panel.get_config())
        values.update(self.review_panel.get_config())
        values.update(self.extra_prompts_panel.get_config())
        return values
