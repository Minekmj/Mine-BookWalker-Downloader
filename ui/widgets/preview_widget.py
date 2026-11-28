from typing import Optional

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


class CutlinePreviewWidget(QWidget):
    cutlineChanged = Signal(float)
    sideCropChanged = Signal(float, float)
    wheelPageChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(320)
        self.setMinimumHeight(420)
        self.setMouseTracking(True)

        self._pixmap: Optional[QPixmap] = None
        self._edit_pixmap: Optional[QPixmap] = None
        self._top_pct: float = 3.0
        self._cutline_enabled: bool = True
        self._hover_only: bool = False
        self._hover_edit: bool = False
        self._dragging: bool = False
        self._side_crop_enabled: bool = False
        self._left_pct: float = 0.0
        self._right_pct: float = 0.0
        self._side_dragging: Optional[str] = None
        self._img_rect = QRectF()

    def _to_pixmap(self, img: Optional[Image.Image]) -> Optional[QPixmap]:
        if img is None:
            return None
        rgb = img.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
        return QPixmap.fromImage(qimg.copy())

    def set_image(self, img: Optional[Image.Image], edit_image: Optional[Image.Image] = None):
        self._pixmap = self._to_pixmap(img)
        self._edit_pixmap = self._to_pixmap(edit_image)
        self._hover_edit = False
        self._dragging = False
        self._side_dragging = None
        self.update()

    def set_qimage(self, qimg: Optional[QImage], edit_qimg: Optional[QImage] = None):
        self._pixmap = QPixmap.fromImage(qimg) if qimg is not None and not qimg.isNull() else None
        self._edit_pixmap = QPixmap.fromImage(edit_qimg) if edit_qimg is not None and not edit_qimg.isNull() else None
        self._hover_edit = False
        self._dragging = False
        self._side_dragging = None
        self.update()

    def set_hover_only(self, enabled: bool):
        self._hover_only = bool(enabled)
        self._hover_edit = False
        self.update()

    def set_cutline_enabled(self, enabled: bool):
        self._cutline_enabled = enabled
        self.update()

    def set_top_pct(self, top_pct: float):
        self._top_pct = max(0.0, min(45.0, float(top_pct)))
        self.update()

    def set_side_crop_enabled(self, enabled: bool):
        self._side_crop_enabled = bool(enabled)
        if not self._side_crop_enabled:
            self._side_dragging = None
        self.update()

    def set_side_crop_pcts(self, left_pct: float, right_pct: float):
        lp = max(0.0, min(49.0, float(left_pct)))
        rp = max(0.0, min(49.0, float(right_pct)))
        if lp + rp > 95.0:
            rp = max(0.0, 95.0 - lp)
        self._left_pct = lp
        self._right_pct = rp
        self.update()

    def _calc_image_rect(self, pixmap: Optional[QPixmap] = None) -> QRectF:
        pixmap = pixmap or self._pixmap
        if not pixmap or pixmap.isNull():
            return QRectF()
        pw, ph = pixmap.width(), pixmap.height()
        avail = self.rect().adjusted(10, 10, -10, -10)
        if avail.width() <= 0 or avail.height() <= 0:
            return QRectF()
        scale = min(avail.width() / pw, avail.height() / ph)
        dw, dh = pw * scale, ph * scale
        x = avail.x() + (avail.width() - dw) / 2.0
        y = avail.y() + (avail.height() - dh) / 2.0
        return QRectF(x, y, dw, dh)

    def _draw_side_cutlines(self, painter: QPainter, rect: QRectF):
        x_left = rect.left() + rect.width() * (self._left_pct / 100.0)
        x_right = rect.right() - rect.width() * (self._right_pct / 100.0)
        if self._left_pct > 0:
            painter.fillRect(QRectF(rect.left(), rect.top(), x_left - rect.left(), rect.height()), QColor(185, 28, 28, 70))
        if self._right_pct > 0:
            painter.fillRect(QRectF(x_right, rect.top(), rect.right() - x_right, rect.height()), QColor(185, 28, 28, 70))

        for x_pos in (x_left, x_right):
            painter.setPen(QPen(QColor(255, 255, 255, 220), 3, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(x_pos, rect.top()), QPointF(x_pos, rect.bottom()))
            painter.setPen(QPen(QColor("#b91c1c"), 1.8, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(x_pos, rect.top()), QPointF(x_pos, rect.bottom()))

        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()

        left_label = f"좌측 {self._left_pct:.1f}%"
        ltw = fm.horizontalAdvance(left_label) + 12
        lth = fm.height() + 4
        lbx = min(rect.right() - ltw - 2, max(rect.left() + 2, x_left + 4))
        lby = min(rect.bottom() - lth - 2, rect.top() + max(6.0, rect.height() * 0.12))
        lpill = QRectF(lbx, lby, ltw, lth)
        painter.setBrush(QColor("#b91c1c"))
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawRoundedRect(lpill, 4, 4)
        painter.drawText(lpill, Qt.AlignmentFlag.AlignCenter, left_label)

        right_label = f"우측 {self._right_pct:.1f}%"
        rtw = fm.horizontalAdvance(right_label) + 12
        rth = fm.height() + 4
        rbx = max(rect.left() + 2, min(rect.right() - rtw - 2, x_right - rtw - 4))
        rby = min(rect.bottom() - rth - 2, lby + lth + 6)
        rpill = QRectF(rbx, rby, rtw, rth)
        painter.setBrush(QColor("#b91c1c"))
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawRoundedRect(rpill, 4, 4)
        painter.drawText(rpill, Qt.AlignmentFlag.AlignCenter, right_label)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#2e313d"))

        if not self._pixmap or self._pixmap.isNull():
            painter.setPen(QColor("#6b7280"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "폴더를 선택하면 미리보기가 표시됩니다.")
            return

        active_pixmap = self._edit_pixmap if self._hover_edit and self._edit_pixmap else self._pixmap
        rect = self._calc_image_rect(active_pixmap)
        self._img_rect = rect
        painter.drawPixmap(rect.toRect(), active_pixmap)

        if self._side_crop_enabled:
            self._draw_side_cutlines(painter, rect)

        if not self._cutline_enabled or (self._hover_only and not self._hover_edit):
            return

        y_top = rect.top() + rect.height() * (self._top_pct / 100.0)
        if self._top_pct > 0:
            painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), y_top - rect.top()), QColor(185, 28, 28, 70))

        painter.setPen(QPen(QColor(255, 255, 255, 220), 3, Qt.PenStyle.SolidLine))
        painter.drawLine(QPointF(rect.left(), y_top), QPointF(rect.right(), y_top))

        painter.setPen(QPen(QColor("#b91c1c"), 1.8, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(rect.left(), y_top), QPointF(rect.right(), y_top))

        label = f"상단 제거 {self._top_pct:.1f}%"
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label) + 12
        th = fm.height() + 4
        bx = rect.center().x() - tw / 2.0
        by = min(rect.bottom() - th - 2, max(rect.top() + 2, y_top + 3))

        pill = QRectF(bx, by, tw, th)
        painter.setBrush(QColor("#b91c1c"))
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawRoundedRect(pill, 4, 4)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self.wheelPageChanged.emit(-1)
        elif delta < 0:
            self.wheelPageChanged.emit(1)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._img_rect.isEmpty():
            if self._side_crop_enabled:
                x_left = self._img_rect.left() + self._img_rect.width() * (self._left_pct / 100.0)
                x_right = self._img_rect.right() - self._img_rect.width() * (self._right_pct / 100.0)
                dl = abs(event.position().x() - x_left)
                dr = abs(event.position().x() - x_right)
                if min(dl, dr) <= 18:
                    self._side_dragging = "left" if dl <= dr else "right"
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                    event.accept()
                    return
            if self._cutline_enabled and (not self._hover_only or self._hover_edit):
                y_top = self._img_rect.top() + self._img_rect.height() * (self._top_pct / 100.0)
                if abs(event.position().y() - y_top) <= 15:
                    self._dragging = True
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._side_dragging and not self._img_rect.isEmpty():
            w = max(1.0, self._img_rect.width())
            if self._side_dragging == "left":
                pct = ((pos.x() - self._img_rect.left()) / w) * 100.0
                max_pct = min(49.0, 95.0 - self._right_pct)
                self._left_pct = round(max(0.0, min(max_pct, pct)) * 2) / 2.0
            else:
                pct = ((self._img_rect.right() - pos.x()) / w) * 100.0
                max_pct = min(49.0, 95.0 - self._left_pct)
                self._right_pct = round(max(0.0, min(max_pct, pct)) * 2) / 2.0
            self.update()
            self.sideCropChanged.emit(self._left_pct, self._right_pct)
            event.accept()
            return

        if self._dragging and not self._img_rect.isEmpty():
            h = max(1.0, self._img_rect.height())
            pct = ((pos.y() - self._img_rect.top()) / h) * 100.0
            self._top_pct = round(max(0.0, min(45.0, pct)) * 2) / 2.0
            self.update()
            self.cutlineChanged.emit(self._top_pct)
            event.accept()
            return

        if self._side_crop_enabled and not self._img_rect.isEmpty():
            x_left = self._img_rect.left() + self._img_rect.width() * (self._left_pct / 100.0)
            x_right = self._img_rect.right() - self._img_rect.width() * (self._right_pct / 100.0)
            if abs(pos.x() - x_left) <= 18 or abs(pos.x() - x_right) <= 18:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
                super().mouseMoveEvent(event)
                return

        if self._hover_only and self._cutline_enabled and self._edit_pixmap and not self._dragging:
            if self._hover_edit:
                if not self._img_rect.adjusted(-8, -8, 8, 8).contains(pos):
                    self._hover_edit = False
                    self.update()
            else:
                normal_rect = self._calc_image_rect(self._pixmap)
                if normal_rect.contains(pos) and pos.y() <= normal_rect.top() + min(42.0, normal_rect.height() * 0.12):
                    self._hover_edit = True
                    self.update()
        if self._cutline_enabled and not self._img_rect.isEmpty() and (not self._hover_only or self._hover_edit):
            y_top = self._img_rect.top() + self._img_rect.height() * (self._top_pct / 100.0)
            hit = abs(pos.y() - y_top) <= 18
            self.setCursor(Qt.CursorShape.SizeVerCursor if hit else Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_only and not self._dragging:
            self._hover_edit = False
            self.update()
        if not self._dragging and not self._side_dragging:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._side_dragging and event.button() == Qt.MouseButton.LeftButton:
            self._side_dragging = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
