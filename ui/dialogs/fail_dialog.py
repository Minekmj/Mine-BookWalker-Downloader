from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
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
    QVBoxLayout,
)

from ui.panels.gemini_panel import GEMINI_MODEL_PRESETS


class FailureReviewDialog(QDialog):
    def __init__(self, payload: dict, current_settings: dict, parent=None):
        super().__init__(parent)
        self.payload = payload
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
        self.lbl_img = QLabel()
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setMinimumSize(340, 400)
        self._set_pil_image(payload["image"])
        img_layout.addWidget(self.lbl_img)

        txt_box = QGroupBox("추출 결과 (직접 수정 가능)")
        txt_layout = QVBoxLayout(txt_box)
        self.edit_text = QPlainTextEdit()
        self.edit_text.setPlainText(payload.get("current_text", ""))
        txt_layout.addWidget(self.edit_text)

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

    def _set_pil_image(self, img):
        if img is None:
            return
        rgb = img.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        self.lbl_img.setPixmap(
            pix.scaled(400, 500, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
