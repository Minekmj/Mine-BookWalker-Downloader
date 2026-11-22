from typing import List, Optional, Tuple

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QScrollArea, QWidget

_ROTATE_CHARS = set("ー―─━〜～「」『』（）()【】〔〕〈〉《》［］[]…‥：；=")
_TOP_RIGHT_CHARS = set("。、，．")
_SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ")


class _VerticalCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._highlights: List[Tuple[int, int, QColor, QColor]] = []
        self._columns: List[List[Tuple[str, int]]] = []
        self._cell_w = 17
        self._cell_h = 15
        self._col_gap = 3
        self._pad = 10
        self._font = QFont("Yu Mincho", 10)
        self._font.setStyleHint(QFont.StyleHint.Serif)
        self.setStyleSheet("background-color: #fafafa;")

    def set_content(self, text: str, highlights: Optional[List[Tuple[int, int, QColor, QColor]]] = None, max_rows: int = 24):
        self._text = text or ""
        self._highlights = highlights or []
        self._columns = []
        rows_cap = max(10, max_rows)
        pos = 0
        lines = self._text.split("\n")
        for line_idx, line in enumerate(lines):
            if not line:
                self._columns.append([])
            else:
                cur_col: List[Tuple[str, int]] = []
                for offset, ch in enumerate(line):
                    cur_col.append((ch, pos + offset))
                    if len(cur_col) >= rows_cap:
                        self._columns.append(cur_col)
                        cur_col = []
                if cur_col:
                    self._columns.append(cur_col)
            pos += len(line) + (1 if line_idx < len(lines) - 1 else 0)

        col_step = self._cell_w + self._col_gap
        total_w = max(280, self._pad * 2 + max(1, len(self._columns)) * col_step)
        max_len = max((len(c) for c in self._columns), default=1)
        total_h = max(180, self._pad * 2 + min(max_len, rows_cap) * self._cell_h)
        self.setMinimumSize(total_w, total_h)
        self.resize(total_w, total_h)
        self.update()

    def _find_highlight(self, char_idx: int) -> Optional[Tuple[QColor, QColor]]:
        for s, e, fg, bg in self._highlights:
            if s <= char_idx < e:
                return fg, bg
        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.fillRect(self.rect(), QColor("#fafafa"))

        col_step = self._cell_w + self._col_gap
        start_x = self.width() - self._pad - self._cell_w
        base_fg = QColor("#1f2328")

        for col_idx, col in enumerate(self._columns):
            x = start_x - col_idx * col_step
            for row_idx, (ch, char_idx) in enumerate(col):
                y = self._pad + row_idx * self._cell_h
                cell_rect = QRectF(x, y, self._cell_w, self._cell_h)
                hl = self._find_highlight(char_idx)
                if hl is not None:
                    fg, bg = hl
                    painter.fillRect(cell_rect, bg)
                    f = QFont(self._font)
                    f.setBold(True)
                    painter.setFont(f)
                    painter.setPen(fg)
                else:
                    painter.setFont(self._font)
                    painter.setPen(base_fg)

                if ch in _ROTATE_CHARS:
                    painter.save()
                    cx = cell_rect.center().x()
                    cy = cell_rect.center().y()
                    painter.translate(cx, cy)
                    painter.rotate(90)
                    painter.drawText(
                        QRectF(-self._cell_h / 2, -self._cell_w / 2, self._cell_h, self._cell_w),
                        Qt.AlignmentFlag.AlignCenter,
                        ch,
                    )
                    painter.restore()
                elif ch in _TOP_RIGHT_CHARS:
                    shifted = QRectF(x + self._cell_w * 0.25, y - self._cell_h * 0.22, self._cell_w, self._cell_h)
                    painter.drawText(shifted, Qt.AlignmentFlag.AlignCenter, ch)
                elif ch in _SMALL_KANA:
                    shifted = QRectF(x + self._cell_w * 0.08, y - self._cell_h * 0.06, self._cell_w, self._cell_h)
                    painter.drawText(shifted, Qt.AlignmentFlag.AlignCenter, ch)
                else:
                    painter.drawText(cell_rect, Qt.AlignmentFlag.AlignCenter, ch)


class VerticalTextView(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(False)
        self._canvas = _VerticalCanvas(self)
        self.setWidget(self._canvas)
        self._last_text = ""
        self._last_highlights: List[Tuple[int, int, QColor, QColor]] = []

    def _calc_max_rows(self) -> int:
        avail_h = max(180, self.viewport().height() - 28)
        return max(12, avail_h // self._canvas._cell_h)

    def set_text(self, text: str, highlights: Optional[List[Tuple[int, int, QColor, QColor]]] = None):
        self._last_text = text or ""
        self._last_highlights = highlights or []
        self._canvas.set_content(self._last_text, self._last_highlights, max_rows=self._calc_max_rows())
        sb = self.horizontalScrollBar()
        sb.setValue(sb.maximum())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._last_text:
            self._canvas.set_content(self._last_text, self._last_highlights, max_rows=self._calc_max_rows())
            sb = self.horizontalScrollBar()
            sb.setValue(sb.maximum())
