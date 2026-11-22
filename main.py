import sys
from pathlib import Path

from PySide6.QtCore import QDir, QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

from path_clean import app_path, get_app_dir, get_resource_dir, resource_path

ROOT_DIR = get_app_dir()
RES_DIR = get_resource_dir()
for _p in (str(RES_DIR), str(ROOT_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.config.paths import ensure_app_dirs
from ui.main_window import MainWindow


def ensure_qss_icons(icon_dir: Path):
    try:
        icon_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    check_path = icon_dir / "check.png"
    if not check_path.is_file():
        pm = QPixmap(14, 14)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#ffffff"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline([QPointF(3.0, 7.2), QPointF(5.8, 10.2), QPointF(11.0, 4.0)])
        p.end()
        pm.save(str(check_path))

    for name, pts in [
        ("arrow_down.png", [QPointF(2.5, 4.2), QPointF(6.0, 8.0), QPointF(9.5, 4.2)]),
        ("arrow_up.png", [QPointF(2.5, 7.8), QPointF(6.0, 4.0), QPointF(9.5, 7.8)]),
    ]:
        out_path = icon_dir / name
        if out_path.is_file():
            continue
        pm = QPixmap(12, 12)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#475569"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPolyline(pts)
        p.end()
        pm.save(str(out_path))


def apply_light_palette(app: QApplication):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#f6f7f9"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#1f2328"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#f8f9fa"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#1f2328"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#1f2328"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#334155"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9ca3af"))
    app.setPalette(pal)


def load_qss(app: QApplication):
    icon_dir = resource_path("qss", "icons")
    ensure_qss_icons(icon_dir)
    QDir.addSearchPath("icons", str(icon_dir))

    qss_path = resource_path("qss", "style.qss")
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))


def main():
    ensure_app_dirs()
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resource_path("qss", "icons", "icon.ico"))))
    app.setStyle("Fusion")
    apply_light_palette(app)
    load_qss(app)
    window = MainWindow(settings_path=app_path("settings.json"))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
