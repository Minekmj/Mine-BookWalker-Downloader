from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

class CoverCropCanvas(QWidget):
    def __init__(self, image: Image.Image, parent=None):
        super().__init__(parent)
        rgb = image.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
        self.pixmap = QPixmap.fromImage(qimage.copy())
        self.image_rect = QRectF()
        self.selection = QRectF()
        self.drag_start = None
        self.setMinimumSize(520, 560)
        self.setMouseTracking(True)

    def _fit_rect(self):
        if self.pixmap.isNull():
            return QRectF()
        available = self.rect().adjusted(12, 12, -12, -12)
        scale = min(available.width() / self.pixmap.width(), available.height() / self.pixmap.height())
        width = self.pixmap.width() * scale
        height = self.pixmap.height() * scale
        return QRectF(available.center().x() - width / 2, available.center().y() - height / 2, width, height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#20242b"))
        self.image_rect = self._fit_rect()
        if self.pixmap.isNull() or self.image_rect.isEmpty():
            return
        painter.drawPixmap(self.image_rect.toRect(), self.pixmap)
        if self.selection.isEmpty():
            painter.setPen(QColor("white"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, "드래그해서 표지로 사용할 영역을 선택하세요")
            return
        selected = self.selection.intersected(self.image_rect)
        shade = QColor(0, 0, 0, 130)
        painter.fillRect(QRectF(self.image_rect.left(), self.image_rect.top(), self.image_rect.width(), max(0, selected.top() - self.image_rect.top())), shade)
        painter.fillRect(QRectF(self.image_rect.left(), selected.bottom(), self.image_rect.width(), max(0, self.image_rect.bottom() - selected.bottom())), shade)
        painter.fillRect(QRectF(self.image_rect.left(), selected.top(), max(0, selected.left() - self.image_rect.left()), selected.height()), shade)
        painter.fillRect(QRectF(selected.right(), selected.top(), max(0, self.image_rect.right() - selected.right()), selected.height()), shade)
        painter.setPen(QPen(QColor("#facc15"), 2))
        painter.drawRect(selected)

    def _clamp(self, point: QPointF):
        return QPointF(max(self.image_rect.left(), min(self.image_rect.right(), point.x())), max(self.image_rect.top(), min(self.image_rect.bottom(), point.y())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.image_rect.contains(event.position()):
            self.drag_start = self._clamp(event.position())
            self.selection = QRectF(self.drag_start, self.drag_start)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start is not None:
            self.selection = QRectF(self.drag_start, self._clamp(event.position())).normalized().intersected(self.image_rect)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            self.selection = QRectF(self.drag_start, self._clamp(event.position())).normalized().intersected(self.image_rect)
            self.drag_start = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def normalized_rect(self):
        selected = self.selection.intersected(self.image_rect)
        if selected.isEmpty() or selected.width() < 10 or selected.height() < 10:
            return None
        return ((selected.left() - self.image_rect.left()) / self.image_rect.width(), (selected.top() - self.image_rect.top()) / self.image_rect.height(), selected.width() / self.image_rect.width(), selected.height() / self.image_rect.height())

class CoverCropDialog(QDialog):
    def __init__(self, image: Image.Image, parent=None):
        super().__init__(parent)
        self.setWindowTitle("첫 장 표지 영역 자르기")
        self.resize(720, 780)
        self.selected_rect = None
        layout = QVBoxLayout(self)
        label = QLabel("첫 번째 이미지에서 표지로 사용할 부분만 드래그해 선택하세요. 이 선택은 첫 장에만 적용되며 자동 여백 제거는 하지 않습니다.")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.canvas = CoverCropCanvas(image, self)
        layout.addWidget(self.canvas, 1)
        buttons = QHBoxLayout()
        self.btn_full = QPushButton("전체 이미지 사용")
        self.btn_cancel = QPushButton("취소")
        self.btn_apply = QPushButton("선택 영역 적용")
        self.btn_full.clicked.connect(self._use_full)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._apply_selection)
        buttons.addWidget(self.btn_full)
        buttons.addStretch()
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_apply)
        layout.addLayout(buttons)

    def _use_full(self):
        self.selected_rect = (0.0, 0.0, 1.0, 1.0)
        self.accept()

    def _apply_selection(self):
        rect = self.canvas.normalized_rect()
        if rect is None:
            QMessageBox.warning(self, "영역 선택 필요", "이미지 위에서 표지 영역을 드래그하세요.")
            return
        self.selected_rect = rect
        self.accept()
