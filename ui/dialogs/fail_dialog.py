from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
)

from ui.panels.gemini_panel import GEMINI_MODEL_PRESETS
from ui.widgets.vertical_text_view import VerticalTextView


class FailureReviewDialog(QDialog):
    def __init__(self, payload: dict, current_settings: dict, parent=None):
        super().__init__(parent)
        self.payload = payload
        self._raw_image = payload.get("image")
        self._decision = {"action": "keep"}

        page_no = payload["page_no"]
        src_name = payload.get("source_name", "")
        self.setWindowTitle(f"페이지 확인 필요 — p{page_no} ({src_name})")
        self.resize(960, 640)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        info_text = (
            f"페이지: {page_no} ({src_name})  |  "
            f"사유: {payload.get('reason', '')}  |  "
            f"실제 {payload.get('actual_chars', 0)}자 / 예상 {payload.get('expected_chars', 0)}자 "
            f"(Z={payload.get('z_score', 0.0)})"
        )
        lbl_info = QLabel(info_text)
        lbl_info.setObjectName("statusWarn")
        lbl_info.setWordWrap(True)
        root.addWidget(lbl_info)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        img_box = QGroupBox("페이지 이미지")
        img_layout = QVBoxLayout(img_box)
        img_ctrl = QHBoxLayout()
        self.chk_rotate_ccw = QCheckBox("이미지 -90° 회전")
        self.chk_rotate_ccw.toggled.connect(self._render_image)
        img_ctrl.addWidget(self.chk_rotate_ccw)
        img_ctrl.addStretch()
        img_layout.addLayout(img_ctrl)

        self.lbl_img = QLabel()
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setMinimumSize(340, 400)
        img_layout.addWidget(self.lbl_img, 1)
        self._render_image()

        txt_box = QGroupBox("추출 결과 (직접 수정 가능)")
        txt_layout = QVBoxLayout(txt_box)
        txt_ctrl = QHBoxLayout()
        self.chk_vertical_text = QCheckBox("글자 세로쓰기 (일본어)")
        self.chk_vertical_text.toggled.connect(self._toggle_vertical_text)
        txt_ctrl.addWidget(self.chk_vertical_text)
        txt_ctrl.addStretch()
        txt_layout.addLayout(txt_ctrl)

        self.txt_stack = QStackedWidget()
        self.edit_text = QPlainTextEdit()
        self.edit_text.setPlainText(payload.get("current_text", ""))
        self.vert_text = VerticalTextView()
        self.txt_stack.addWidget(self.edit_text)
        self.txt_stack.addWidget(self.vert_text)
        txt_layout.addWidget(self.txt_stack, 1)

        splitter.addWidget(img_box)
        splitter.addWidget(txt_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        retry_group = QGroupBox("처리 방법 선택")
        rg = QGridLayout(retry_group)
        rg.setSpacing(8)

        self.combo_model = QComboBox()
        self.combo_model.setEditable(True)
        cur_model = payload.get("current_model") or current_settings.get("gemini_model", "gemini-3.1-flash-lite")
        for m in list(dict.fromkeys([cur_model] + GEMINI_MODEL_PRESETS)):
            self.combo_model.addItem(m, m)
        self.combo_model.setCurrentText(cur_model)

        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 1.0)
        self.spin_temp.setSingleStep(0.01)
        self.spin_temp.setDecimals(2)
        next_temp = min(0.85, float(payload.get("current_temp", 0.35)) + float(current_settings.get("gemini_temp_step", 0.2)))
        self.spin_temp.setValue(next_temp)

        self.chk_apply_all = QCheckBox("남은 오류 페이지에도 같은 동작 적용")

        rg.addWidget(QLabel("재시도 모델"), 0, 0)
        rg.addWidget(self.combo_model, 0, 1)
        rg.addWidget(QLabel("재시도 온도"), 0, 2)
        rg.addWidget(self.spin_temp, 0, 3)
        rg.addWidget(self.chk_apply_all, 0, 4)

        btn_row = QHBoxLayout()
        btn_retry_gemini = QPushButton("다시 시도")
        btn_retry_gemini.setObjectName("primaryBtn")
        btn_retry_gemini.clicked.connect(lambda: self._choose("retry_gemini"))

        btn_illust = QPushButton("삽화(이미지)로 저장")
        btn_illust.clicked.connect(lambda: self._choose("illustration"))

        btn_keep = QPushButton("텍스트 그대로 계속")
        btn_keep.clicked.connect(lambda: self._choose("keep_edited"))

        btn_skip = QPushButton("건너뛰기")
        btn_skip.setObjectName("dangerBtn")
        btn_skip.clicked.connect(lambda: self._choose("skip"))

        btn_row.addWidget(btn_retry_gemini)
        btn_row.addWidget(btn_illust)
        btn_row.addWidget(btn_keep)
        btn_row.addWidget(btn_skip)
        rg.addLayout(btn_row, 1, 0, 1, 5)

        root.addWidget(retry_group)

    def _toggle_vertical_text(self, checked: bool):
        if checked:
            self.vert_text.set_text(self.edit_text.toPlainText())
            self.txt_stack.setCurrentWidget(self.vert_text)
        else:
            self.txt_stack.setCurrentWidget(self.edit_text)

    def _render_image(self):
        if self._raw_image is None:
            return
        rgb = self._raw_image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        if self.chk_rotate_ccw.isChecked():
            pix = pix.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
        target_w = max(360, self.lbl_img.width() or 420)
        target_h = max(400, self.lbl_img.height() or 500)
        self.lbl_img.setPixmap(
            pix.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def _choose(self, action: str):
        self._decision = {
            "action": action,
            "model": self.combo_model.currentText().strip(),
            "temperature": self.spin_temp.value(),
            "edited_text": self.edit_text.toPlainText(),
            "apply_all": self.chk_apply_all.isChecked(),
        }
        self.accept()

    def get_decision(self) -> dict:
        return self._decision
