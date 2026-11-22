from difflib import SequenceMatcher
from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImage, QPixmap, QTextCharFormat, QTextCursor, QTransform
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
)

from ui.widgets.vertical_text_view import VerticalTextView


class CorrectionPreviewDialog(QDialog):
    def __init__(self, payload: dict, parent=None):
        super().__init__(parent)
        self.payload = payload
        self._raw_image = payload.get("image")
        self._decision = {"action": "keep"}
        self._old_highlights: List[Tuple[int, int, QColor, QColor]] = []
        self._new_highlights: List[Tuple[int, int, QColor, QColor]] = []

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

        ctrl_row = QHBoxLayout()
        self.chk_rotate_ccw = QCheckBox("이미지 -90° 회전")
        self.chk_rotate_ccw.toggled.connect(self._render_image)
        self.chk_vertical_text = QCheckBox("글자 세로쓰기 (일본어)")
        self.chk_vertical_text.toggled.connect(self._toggle_vertical_text)
        ctrl_row.addWidget(self.chk_rotate_ccw)
        ctrl_row.addWidget(self.chk_vertical_text)
        ctrl_row.addStretch()
        root.addLayout(ctrl_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        img_box = QGroupBox("페이지 이미지")
        img_layout = QVBoxLayout(img_box)
        self.lbl_img = QLabel()
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setMinimumSize(280, 400)
        img_layout.addWidget(self.lbl_img, 1)
        self._render_image()

        old_text = str(payload.get("old_text", "") or "").replace("\r\n", "\n")
        new_text = str(payload.get("new_text", "") or "").replace("\r\n", "\n")

        old_box = QGroupBox("기존 OCR 텍스트 (삭제 부분 빨간색 표시)")
        old_layout = QVBoxLayout(old_box)
        self.old_stack = QStackedWidget()
        self.edit_old = QPlainTextEdit()
        self.edit_old.setReadOnly(True)
        self.edit_old.setPlainText(old_text)
        self.vert_old = VerticalTextView()
        self.old_stack.addWidget(self.edit_old)
        self.old_stack.addWidget(self.vert_old)
        old_layout.addWidget(self.old_stack)

        new_box = QGroupBox("검수 수정안 (직접 편집 가능 · 추가 부분 노란색 표시)")
        new_layout = QVBoxLayout(new_box)
        self.new_stack = QStackedWidget()
        self.edit_new = QPlainTextEdit()
        self.edit_new.setPlainText(new_text)
        self.vert_new = VerticalTextView()
        self.new_stack.addWidget(self.edit_new)
        self.new_stack.addWidget(self.vert_new)
        new_layout.addWidget(self.new_stack)

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

    def _toggle_vertical_text(self, checked: bool):
        if checked:
            old_t = self.edit_old.toPlainText()
            new_t = self.edit_new.toPlainText()
            self._apply_diff_highlights(old_t, new_t)
            self.vert_old.set_text(old_t, self._old_highlights)
            self.vert_new.set_text(new_t, self._new_highlights)
            self.old_stack.setCurrentWidget(self.vert_old)
            self.new_stack.setCurrentWidget(self.vert_new)
        else:
            self.old_stack.setCurrentWidget(self.edit_old)
            self.new_stack.setCurrentWidget(self.edit_new)

    def _apply_diff_highlights(self, old_text: str, new_text: str):
        del_fg, del_bg = QColor("#b91c1c"), QColor("#fee2e2")
        add_fg, add_bg = QColor("#92400e"), QColor("#fef08a")

        del_fmt = QTextCharFormat()
        del_fmt.setForeground(del_fg)
        del_fmt.setBackground(del_bg)
        del_fmt.setFontWeight(QFont.Weight.Bold)

        add_fmt = QTextCharFormat()
        add_fmt.setForeground(add_fg)
        add_fmt.setBackground(add_bg)
        add_fmt.setFontWeight(QFont.Weight.Bold)

        old_selections = []
        new_selections = []
        self._old_highlights = []
        self._new_highlights = []
        matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag in ("delete", "replace") and i2 > i1:
                self._old_highlights.append((i1, i2, del_fg, del_bg))
                cur_old = self.edit_old.textCursor()
                cur_old.setPosition(i1)
                cur_old.setPosition(i2, QTextCursor.MoveMode.KeepAnchor)
                sel_old = QTextEdit.ExtraSelection()
                sel_old.cursor = cur_old
                sel_old.format = del_fmt
                old_selections.append(sel_old)
            if tag in ("insert", "replace") and j2 > j1:
                self._new_highlights.append((j1, j2, add_fg, add_bg))
                cur_new = self.edit_new.textCursor()
                cur_new.setPosition(j1)
                cur_new.setPosition(j2, QTextCursor.MoveMode.KeepAnchor)
                sel_new = QTextEdit.ExtraSelection()
                sel_new.cursor = cur_new
                sel_new.format = add_fmt
                new_selections.append(sel_new)

        self.edit_old.setExtraSelections(old_selections)
        self.edit_new.setExtraSelections(new_selections)

    def _render_image(self):
        if self._raw_image is None:
            self.lbl_img.setText("이미지를 불러올 수 없습니다.")
            return
        rgb = self._raw_image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg.copy())
        if self.chk_rotate_ccw.isChecked():
            pix = pix.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
        target_w = max(320, self.lbl_img.width() or 380)
        target_h = max(400, self.lbl_img.height() or 520)
        self.lbl_img.setPixmap(
            pix.scaled(target_w, target_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
