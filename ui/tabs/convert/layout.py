from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QWheelEvent

from ui.widgets.log_box import ColorLogBox
from ui.widgets.preview_widget import CutlinePreviewWidget

class NoWheelComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()

class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()
        
class LayoutMixin():
    def _build_path_group(self) -> QGroupBox:
        box = QGroupBox("대상 폴더")
        g = QGridLayout(box)
        g.setSpacing(8)

        self.input_edit = QLineEdit()
        self.input_edit.setMinimumWidth(80)
        self.input_edit.setPlaceholderText("이미지 폴더 선택")
        btn_in = QPushButton("폴더 선택")
        btn_in.clicked.connect(self._browse_input)

        self.book_title_edit = QLineEdit()
        self.book_title_edit.setMinimumWidth(80)
        self.book_title_edit.setPlaceholderText("책 제목 (비우면 폴더명)")

        g.addWidget(QLabel("원본 폴더"), 0, 0)
        g.addWidget(self.input_edit, 0, 1)
        g.addWidget(btn_in, 0, 2)

        g.addWidget(QLabel("제목"), 1, 0)
        g.addWidget(self.book_title_edit, 1, 1, 1, 2)
        return box

    def _build_options_group(self) -> QWidget:
        root = QWidget()
        root.setObjectName("settingsContent")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(2, 4, 8, 8)
        outer.setSpacing(12)

        format_box = QGroupBox("출력 형식")
        format_layout = QVBoxLayout(format_box)
        format_layout.setContentsMargins(12, 18, 12, 12)
        format_layout.setSpacing(6)
        self.format_combo = NoWheelComboBox()
        self.format_combo.addItem("라노벨 · EPUB", "novel")
        self.format_combo.addItem("만화 · PDF", "manga_pdf")
        self.format_combo.addItem("만화 · ZIP", "manga_zip")
        self.format_combo.currentIndexChanged.connect(self._on_mode_changed)
        format_layout.addWidget(self.format_combo)
        format_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(format_box)

        split_box = QGroupBox("페이지 분할")
        split_layout = QVBoxLayout(split_box)
        split_layout.setContentsMargins(12, 18, 12, 12)
        split_layout.setSpacing(8)
        self.chk_split = QCheckBox("좌우 페이지 2분할")
        self.chk_split.setChecked(True)
        self.chk_split.toggled.connect(self._on_preprocess_changed)
        self.chk_split_skip_first = QCheckBox("첫 번째 이미지 제외")
        self.chk_split_skip_first.setChecked(True)
        self.chk_split_skip_first.toggled.connect(self._on_preprocess_changed)
        self.chk_split_large = QCheckBox("긴 삽화도 분할")
        self.chk_split_large.setChecked(False)
        self.chk_split_large.toggled.connect(self._on_preprocess_changed)
        split_layout.addWidget(self.chk_split)
        split_layout.addWidget(self.chk_split_skip_first)
        split_layout.addWidget(self.chk_split_large)
        split_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(split_box)

        self.novel_box = QGroupBox("라노벨 전용 설정")
        novel_layout = QVBoxLayout(self.novel_box)
        novel_layout.setContentsMargins(12, 18, 12, 12)
        novel_layout.setSpacing(10)
        self.chk_trim = QCheckBox("삽화 바깥 여백 제거")
        self.chk_trim.setChecked(True)
        self.chk_trim.toggled.connect(self._on_preprocess_changed)
        novel_layout.addWidget(self.chk_trim)
        self.chk_small_illust = QCheckBox("작은 삽화 인식 (단독 페이지)")
        self.chk_small_illust.setChecked(True)
        self.chk_small_illust.toggled.connect(self._on_preprocess_changed)
        novel_layout.addWidget(self.chk_small_illust)
        self.chk_trim_before_illust = QCheckBox("상단 자르기 후 흰 여백 제거하여 삽화 판단")
        self.chk_trim_before_illust.setChecked(True)
        self.chk_trim_before_illust.toggled.connect(self._on_preprocess_changed)
        novel_layout.addWidget(self.chk_trim_before_illust)
        header_row = QHBoxLayout()
        self.chk_remove_header = QCheckBox("본문 상단 자르기")
        self.chk_remove_header.setChecked(True)
        self.combo_header_cut = NoWheelComboBox()
        self.combo_header_cut.addItem("자동 판단", "auto")
        self.combo_header_cut.addItem("항상 자르기", "always")
        self.combo_header_cut.addItem("자르지 않음", "off")
        self.combo_header_cut.setFixedWidth(150)
        self.combo_header_cut.currentIndexChanged.connect(self._on_header_opts_changed)
        self.chk_remove_header.toggled.connect(self._on_header_opts_changed)
        self.spin_header_top = NoWheelDoubleSpinBox()
        self.spin_header_top.setRange(0.0, 45.0)
        self.spin_header_top.setSingleStep(0.5)
        self.spin_header_top.setDecimals(1)
        self.spin_header_top.setSuffix("%")
        self.spin_header_top.setValue(3.0)
        self.spin_header_top.setFixedWidth(90)
        self.spin_header_top.valueChanged.connect(self._on_header_spin_changed)
        header_row.addWidget(self.chk_remove_header)
        header_row.addWidget(self.combo_header_cut)
        header_row.addWidget(QLabel("제거량"))
        header_row.addWidget(self.spin_header_top)
        header_row.addStretch()
        novel_layout.addLayout(header_row)
        self.chk_crop_illust = QCheckBox("삽화에도 상단 자르기 적용")
        self.chk_crop_illust.setChecked(False)
        self.chk_crop_illust.toggled.connect(self._on_header_opts_changed)
        novel_layout.addWidget(self.chk_crop_illust)

        btn_advanced = QPushButton("이미지 to EPUB 설정")
        btn_advanced.clicked.connect(self._open_advanced_settings)
        novel_layout.addWidget(btn_advanced)

        self.novel_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(self.novel_box)

        self.manga_box = QGroupBox("만화 전용 설정")
        manga_layout = QVBoxLayout(self.manga_box)
        manga_layout.setContentsMargins(12, 18, 12, 12)
        manga_layout.setSpacing(8)
        self.chk_cover_crop = QCheckBox("첫 장 표지 자르기")
        self.chk_cover_crop.setChecked(bool(self.adv.get("cover_crop_enabled", False)))
        self.chk_cover_crop.toggled.connect(self._on_cover_crop_toggled)
        cover_buttons = QHBoxLayout()
        self.btn_cover_crop = QPushButton("영역 직접 선택")
        self.btn_cover_crop.clicked.connect(self._select_cover_crop)
        self.btn_cover_auto = QPushButton("자동 감지")
        self.btn_cover_auto.clicked.connect(self._auto_cover_crop)
        cover_buttons.addWidget(self.btn_cover_crop)
        cover_buttons.addWidget(self.btn_cover_auto)
        cover_buttons.addStretch()
        manga_layout.addWidget(self.chk_cover_crop)
        manga_layout.addLayout(cover_buttons)
        manga_hint = QLabel("표지 자르기는 첫 번째 이미지에만 적용됩니다.")
        manga_hint.setObjectName("hintLabel")
        manga_layout.addWidget(manga_hint)
        self.manga_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        outer.addWidget(self.manga_box)
        outer.addStretch(1)
        return root

    def _build_run_group(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        btn_row = QHBoxLayout()
        self.btn_action = QPushButton("변환 시작")
        self.btn_action.setObjectName("primaryBtn")
        self.btn_action.setMinimumHeight(38)
        self.btn_action.clicked.connect(self._toggle_run_action)

        btn_row.addWidget(self.btn_action)
        v.addLayout(btn_row)

        log_row = QHBoxLayout()
        log_row.setSpacing(8)
        self.btn_log_toggle = QPushButton("▶ 변환 로그")
        self.btn_log_toggle.setCheckable(True)
        self.btn_log_toggle.setObjectName("logToggleBtn")
        self.btn_log_toggle.setMinimumHeight(34)
        self.btn_log_toggle.setStyleSheet("padding: 4px 14px;")
        self.btn_log_toggle.toggled.connect(self._set_log_expanded)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setVisible(False)
        log_row.addWidget(self.btn_log_toggle)
        log_row.addWidget(self.progress_bar, 1)
        v.addLayout(log_row)

        self.lbl_token_usage = QLabel("토큰 사용량 · 입력 0 · 출력 0 · 합계 0")
        self.lbl_token_usage.setObjectName("hintLabel")
        self.lbl_token_usage.setVisible(False)
        v.addWidget(self.lbl_token_usage)

        self.log_box = ColorLogBox()
        self.log_box.setMinimumHeight(140)
        self.log_box.setVisible(False)
        v.addWidget(self.log_box)
        return w

    def _set_log_expanded(self, expanded: bool):
        self.log_box.setVisible(expanded)
        self.progress_bar.setVisible(expanded)
        self.lbl_token_usage.setVisible(expanded)
        self.btn_log_toggle.setText("▼ 변환 로그" if expanded else "▶ 변환 로그")

    def _build_preview_group(self) -> QGroupBox:
        box = QGroupBox("미리보기")
        v = QVBoxLayout(box)
        v.setSpacing(8)

        nav = QHBoxLayout()
        self.btn_prev_page = QPushButton("◀")
        self.btn_prev_page.clicked.connect(self._prev_preview_page)

        self.spin_page_input = QSpinBox()
        self.spin_page_input.setRange(0, 0)
        self.spin_page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_page_input.valueChanged.connect(self._on_page_spin_changed)

        self.lbl_total_pages = QLabel("/ 0")

        self.btn_next_page = QPushButton("▶")
        self.btn_next_page.clicked.connect(self._next_preview_page)

        self.btn_find_text = QPushButton("다음 본문")
        self.btn_find_text.clicked.connect(self._find_next_text_page)
        self.btn_next_illustration = QPushButton("다음 삽화")
        self.btn_next_illustration.clicked.connect(self._find_next_illustration)
        nav.addWidget(self.btn_prev_page)
        nav.addWidget(self.spin_page_input)
        nav.addWidget(self.lbl_total_pages)
        nav.addWidget(self.btn_next_page)
        nav.addWidget(self.btn_find_text)
        nav.addWidget(self.btn_next_illustration)
        v.addLayout(nav)

        preview_opts = QHBoxLayout()
        self.chk_preview_illustration = QCheckBox("현재 페이지를 삽화로 취급")
        self.chk_preview_illustration.toggled.connect(self._on_preview_illustration_toggled)
        self.chk_preview_illust_trim = QCheckBox("이 삽화 여백 제거")
        self.chk_preview_illust_trim.toggled.connect(self._on_preview_illust_trim_toggled)
        self.chk_preview_illust_trim.setVisible(False)
        self.btn_preview_unmerge = QPushButton("합치지 않기")
        self.btn_preview_unmerge.clicked.connect(self._on_preview_unmerge_clicked)
        self.btn_preview_unmerge.setVisible(False)
        preview_opts.addWidget(self.chk_preview_illustration)
        preview_opts.addWidget(self.chk_preview_illust_trim)
        preview_opts.addWidget(self.btn_preview_unmerge)
        preview_opts.addStretch()
        v.addLayout(preview_opts)

        self.lbl_preview_type = QLabel("폴더를 선택하세요")
        self.lbl_preview_type.setObjectName("statusMute")
        v.addWidget(self.lbl_preview_type)

        self.preview_widget = CutlinePreviewWidget()
        self.preview_widget.cutlineChanged.connect(self._on_preview_cutline_dragged)
        self.preview_widget.wheelPageChanged.connect(self._on_preview_wheel)
        v.addWidget(self.preview_widget, 1)
        return box