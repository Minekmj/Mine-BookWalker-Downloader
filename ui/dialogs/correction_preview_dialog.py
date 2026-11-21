from difflib import SequenceMatcher

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
)


class CorrectionPreviewDialog(QDialog):
    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self.payload = payload
        self._decision = {"action": "keep"}

        page_no = payload.get("page_no", 0)
        similarity = float(payload.get("similarity", 0.0))
        reason = str(payload.get("reason", "") or "").strip()
        self.setWindowTitle(f"검수 대량 변경 미리보기 — p{page_no}")
        self.resize(1120, 680)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        info_text = f"페이지: {page_no}  |  원문 유사도: {similarity:.1f}%"
        if reason:
            info_text += f"  |  수정 사유: {reason}"
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
        self.lbl_img.setMinimumSize(280, 400)
        self._set_pil_image(payload.get("image"))
        img_layout.addWidget(self.lbl_img)

        old_text = str(payload.get("old_text", "") or "")
        new_text = str(payload.get("new_text", "") or "")

        old_box = QGroupBox("기존 OCR 텍스트")
        old_layout = QVBoxLayout(old_box)
        self.edit_old = QPlainTextEdit()
        self.edit_old.setReadOnly(True)
        self.edit_old.setPlainText(old_text)
        old_layout.addWidget(self.edit_old)

        new_box = QGroupBox("검수 수정안 (직접 편집 가능 · 변경 부분 노란색 표시)")
        new_layout = QVBoxLayout(new_box)
        self.edit_new = QPlainTextEdit()
        self.edit_new.setPlainText(new_text)
        new_layout.addWidget(self.edit_new)

        self._apply_diff_highlights(old_text, new_text)

        splitter.addWidget(img_box)
        splitter.addWidget(old_box)
        splitter.addWidget(new_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)

        bottom = QHBoxLayout()
        self.chk_apply_all = QCheckBox("남은 대량 변경 페이지에도 같은 선택 적용")
        bottom.addWidget(self.chk_apply_all)
        bottom.addStretch()

        btn_apply = QPushButton("수정안 반영")
        btn_apply.setObjectName("primaryBtn")
        btn_apply.clicked.connect(lambda: self._choose("apply"))

        btn_keep = QPushButton("기존 유지")
        btn_keep.clicked.connect(lambda: self._choose("keep"))

        bottom.addWidget(btn_apply)
        bottom.addWidget(btn_keep)
        root.addLayout(bottom)

    def _apply_diff_highlights(self, old_text: str, new_text: str):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#ca8a04"))
        fmt.setBackground(QColor("#fef9c3"))
        fmt.setFontWeight(QFont.Weight.Bold)

        old_selections = []
        new_selections = []
        matcher = SequenceMatcher(None, old_text, new_text)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if i2 > i1:
                cur_old = self.edit_old.textCursor()
                cur_old.setPosition(i1)
                cur_old.setPosition(i2, QTextCursor.MoveMode.KeepAnchor)
                sel_old = QTextEdit.ExtraSelection()
                sel_old.cursor = cur_old
                sel_old.format = fmt
                old_selections.append(sel_old)
            if j2 > j1:
                cur_new = self.edit_new.textCursor()
                cur_new.setPosition(j1)
                cur_new.setPosition(j2, QTextCursor.MoveMode.KeepAnchor)
                sel_new = QTextEdit.ExtraSelection()
                sel_new.cursor = cur_new
                sel_new.format = fmt
                new_selections.append(sel_new)

        self.edit_old.setExtraSelections(old_selections)
        self.edit_new.setExtraSelections(new_selections)

    def _set_pil_image(self, img):
        if img is None:
            self.lbl_img.setText("이미지를 불러올 수 없습니다.")
            return
        rgb = img.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        self.lbl_img.setPixmap(
            pix.scaled(360, 520, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def _choose(self, action: str):
        self._decision = {
            "action": action,
            "edited_text": self.edit_new.toPlainText(),
            "apply_all": self.chk_apply_all.isChecked(),
        }
        self.accept()

    def get_decision(self) -> dict:
        return self._decision
