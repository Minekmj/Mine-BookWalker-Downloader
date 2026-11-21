from typing import Dict

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QWidget,
)

class EpubDesignPanel(QWidget):

    def __init__(self, initial_settings: Dict, parent=None):
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(0, 0, 0, 0)

        g1 = QGroupBox("레이아웃 · 테마")
        l1 = QGridLayout(g1)
        l1.setSpacing(6)

        self.combo_writing = QComboBox()
        self.combo_writing.addItem("가로쓰기 (일반)", "horizontal")
        self.combo_writing.addItem("세로쓰기 (원서)", "vertical")

        self.combo_theme = QComboBox()
        self.combo_theme.addItem("리더기 기본", "default")
        self.combo_theme.addItem("화이트 (흰 배경)", "light")
        self.combo_theme.addItem("세피아 (미색 종이)", "sepia")
        self.combo_theme.addItem("다크 (어두운 배경)", "dark")

        self.combo_font = QComboBox()
        self.combo_font.addItem("명조체 (소설 기본)", "serif")
        self.combo_font.addItem("고딕체 (산세리프)", "sans")
        self.combo_font.addItem("리더기 기본 글꼴", "inherit")

        self.combo_heading = QComboBox()
        self.combo_heading.addItem("밑줄 제목", "underline")
        self.combo_heading.addItem("가운데 제목", "centered")
        self.combo_heading.addItem("단순 굵은 제목", "simple")

        self.combo_scene = QComboBox()
        self.combo_scene.addItem("＊　＊　＊", "stars")
        self.combo_scene.addItem("원본 기호 유지", "original")
        self.combo_scene.addItem("가로 구분선", "hr")

        for row, (label, widget) in enumerate([
            ("방향", self.combo_writing),
            ("테마", self.combo_theme),
            ("글꼴", self.combo_font),
            ("제목", self.combo_heading),
            ("장면 기호", self.combo_scene),
        ]):
            l1.addWidget(QLabel(label), row, 0)
            l1.addWidget(widget, row, 1)
        l1.setRowStretch(l1.rowCount(), 1)
        root.addWidget(g1, 1)

        g2 = QGroupBox("글자 · 문단 · 페이지")
        l2 = QGridLayout(g2)
        l2.setSpacing(6)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(70, 160)
        self.spin_font_size.setSingleStep(5)
        self.spin_font_size.setSuffix("%")

        self.spin_line_height = QDoubleSpinBox()
        self.spin_line_height.setRange(1.2, 2.6)
        self.spin_line_height.setSingleStep(0.05)
        self.spin_line_height.setDecimals(2)

        self.spin_indent = QDoubleSpinBox()
        self.spin_indent.setRange(0.0, 2.5)
        self.spin_indent.setSingleStep(0.25)
        self.spin_indent.setDecimals(2)
        self.spin_indent.setSuffix("em")

        self.spin_para_gap = QDoubleSpinBox()
        self.spin_para_gap.setRange(0.0, 1.5)
        self.spin_para_gap.setSingleStep(0.05)
        self.spin_para_gap.setDecimals(2)
        self.spin_para_gap.setSuffix("em")

        self.spin_body_margin = QDoubleSpinBox()
        self.spin_body_margin.setRange(0.2, 3.0)
        self.spin_body_margin.setSingleStep(0.1)
        self.spin_body_margin.setDecimals(1)
        self.spin_body_margin.setSuffix("em")

        self.chk_no_indent_dlg = QCheckBox("대화문(「 / \") 들여쓰기 제외")
        self.chk_chap_break = QCheckBox("새 장마다 페이지 나누기")
        self.chk_illust_break = QCheckBox("삽화 다음 페이지 나누기")
        self.chk_cover = QCheckBox("첫 삽화를 표지로 사용")

        l2.addWidget(QLabel("글자 크기"), 0, 0)
        l2.addWidget(self.spin_font_size, 0, 1)
        l2.addWidget(QLabel("줄간격"), 0, 2)
        l2.addWidget(self.spin_line_height, 0, 3)

        l2.addWidget(QLabel("들여쓰기"), 1, 0)
        l2.addWidget(self.spin_indent, 1, 1)
        l2.addWidget(QLabel("문단 간격"), 1, 2)
        l2.addWidget(self.spin_para_gap, 1, 3)

        l2.addWidget(QLabel("여백"), 2, 0)
        l2.addWidget(self.spin_body_margin, 2, 1)

        l2.addWidget(self.chk_no_indent_dlg, 3, 0, 1, 2)
        l2.addWidget(self.chk_chap_break, 3, 2, 1, 2)
        l2.addWidget(self.chk_illust_break, 4, 0, 1, 2)
        l2.addWidget(self.chk_cover, 4, 2, 1, 2)
        l2.setRowStretch(l2.rowCount(), 1)
        root.addWidget(g2, 1)

        self.set_config(initial_settings)

    def get_config(self) -> Dict:
        return {
            "epub_writing_mode": self.combo_writing.currentData(),
            "epub_theme": self.combo_theme.currentData(),
            "epub_font_family": self.combo_font.currentData(),
            "epub_heading_style": self.combo_heading.currentData(),
            "scene_break_style": self.combo_scene.currentData(),
            "epub_font_size_pct": self.spin_font_size.value(),
            "epub_line_height": self.spin_line_height.value(),
            "epub_text_indent_em": self.spin_indent.value(),
            "epub_para_margin_em": self.spin_para_gap.value(),
            "epub_body_margin_em": self.spin_body_margin.value(),
            "epub_no_indent_dialogue": self.chk_no_indent_dlg.isChecked(),
            "epub_chapter_page_break": self.chk_chap_break.isChecked(),
            "epub_illust_page_break": self.chk_illust_break.isChecked(),
            "epub_cover_enabled": self.chk_cover.isChecked(),
        }

    def set_config(self, s: Dict):
        for combo, key, default in [
            (self.combo_writing, "epub_writing_mode", "horizontal"),
            (self.combo_theme, "epub_theme", "default"),
            (self.combo_font, "epub_font_family", "serif"),
            (self.combo_heading, "epub_heading_style", "underline"),
            (self.combo_scene, "scene_break_style", "stars"),
        ]:
            idx = combo.findData(s.get(key, default))
            if idx >= 0:
                combo.setCurrentIndex(idx)

        self.spin_font_size.setValue(int(s.get("epub_font_size_pct", 100)))
        self.spin_line_height.setValue(float(s.get("epub_line_height", 1.85)))
        self.spin_indent.setValue(float(s.get("epub_text_indent_em", 1.0)))
        self.spin_para_gap.setValue(float(s.get("epub_para_margin_em", 0.30)))
        self.spin_body_margin.setValue(float(s.get("epub_body_margin_em", 1.2)))
        self.chk_no_indent_dlg.setChecked(bool(s.get("epub_no_indent_dialogue", True)))
        self.chk_chap_break.setChecked(bool(s.get("epub_chapter_page_break", True)))
        self.chk_illust_break.setChecked(bool(s.get("epub_illust_page_break", True)))
        self.chk_cover.setChecked(bool(s.get("epub_cover_enabled", True)))
