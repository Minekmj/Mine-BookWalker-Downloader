from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import json
import re
import threading
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QComboBox, QFormLayout, QGroupBox, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget
from core.paths import OUT_IMG
from ui.tabs.web_script.template import render_web_script


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", (name or "").strip())
    return cleaned.strip(". ") or "untitled"


class WebScriptTab(QWidget):
    settingsChanged = Signal()

    def __init__(self, initial_settings=None, parent=None):
        super().__init__(parent)
        initial_settings = initial_settings or {}
        self._server_port = self._start_save_server()
        root = QVBoxLayout(self)
        root.setSpacing(16)
        self.combo_dpr = QComboBox()
        self.combo_dpr.addItem("4x 최고화질", 6)
        self.combo_dpr.addItem("3x 초고화질", 5)
        self.combo_dpr.addItem("2x 고화질", 4)
        self.combo_dpr.addItem("1x 원본(권장)", 3)
        dpr_index = self.combo_dpr.findData(int(initial_settings.get("web_dpr_scale", 3)))
        if dpr_index >= 0:
            self.combo_dpr.setCurrentIndex(dpr_index)
        
        self.spin_idle = QSpinBox()
        self.spin_idle.setRange(50, 10000)
        self.spin_idle.setSingleStep(50)
        self.spin_idle.setValue(int(initial_settings.get("web_idle_ms", 2000)))
        self.spin_idle.setSuffix(" ms")
        self.spin_min_wait = QSpinBox()
        self.spin_min_wait.setRange(50, 5000)
        self.spin_min_wait.setSingleStep(50)
        self.spin_min_wait.setValue(int(initial_settings.get("web_min_wait_ms", 600)))
        self.spin_min_wait.setSuffix(" ms")
        self.spin_start_page = QSpinBox()
        self.spin_start_page.setRange(1, 999999)
        self.spin_start_page.setValue(max(1, int(initial_settings.get("web_start_page", 1))))
        self.spin_start_page.setSuffix(" 페이지부터")
        for widget in (self.combo_dpr, self.spin_idle, self.spin_min_wait, self.spin_start_page):
            widget.setMinimumHeight(32)
        cfg_box = QGroupBox("스크립트 설정")
        form = QFormLayout(cfg_box)
        form.setContentsMargins(18, 22, 18, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.addRow("해상도 배율", self.combo_dpr)
        form.addRow("네트워크 대기 (IDLE)", self.spin_idle)
        form.addRow("최소 대기 시간", self.spin_min_wait)
        form.addRow("이어하기 시작 번호", self.spin_start_page)
        root.addWidget(cfg_box)
        script_box = QGroupBox("생성된 자바스크립트 코드")
        sv = QVBoxLayout(script_box)
        sv.setContentsMargins(18, 22, 18, 16)
        sv.setSpacing(12)
        self.script_edit = QPlainTextEdit()
        self.script_edit.setReadOnly(True)
        script_font = QFont("Consolas")
        script_font.setStyleHint(QFont.StyleHint.Monospace)
        self.script_edit.setFont(script_font)
        self.script_edit.setMinimumHeight(180)
        sv.addWidget(self.script_edit, 1)
        self.btn_copy = QPushButton("클립보드에 복사")
        self.btn_copy.setObjectName("primaryBtn")
        self.btn_copy.setMinimumHeight(38)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        sv.addWidget(self.btn_copy)
        hint = QLabel("붙여넣기가 막히면 뷰어 콘솔에 allow pasting 을 입력하고 Enter 후 다시 붙여넣으세요.")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        sv.addWidget(hint)
        root.addWidget(script_box, 1)
        self.combo_dpr.currentIndexChanged.connect(self._on_config_changed)
        self.spin_idle.valueChanged.connect(self._on_config_changed)
        self.spin_min_wait.valueChanged.connect(self._on_config_changed)
        self.spin_start_page.valueChanged.connect(self._on_config_changed)
        self._regenerate_script()

    def _on_config_changed(self, *args):
        self._regenerate_script()
        self.settingsChanged.emit()

    def collect_settings(self):
        return {"web_dpr_scale": int(self.combo_dpr.currentData()), "web_idle_ms": self.spin_idle.value(), "web_min_wait_ms": self.spin_min_wait.value(), "web_start_page": self.spin_start_page.value()}

    def _start_save_server(self) -> int:
        base_dir = Path(OUT_IMG)

        class SaveHandler(BaseHTTPRequestHandler):
            def _send_cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")

            def do_OPTIONS(self):
                self.send_response(204)
                self._send_cors()
                self.end_headers()

            def do_POST(self):
                if self.path != "/save":
                    self.send_response(404)
                    self._send_cors()
                    self.end_headers()
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                    title = _sanitize_name(payload.get("title", ""))
                    filename = Path(payload.get("filename", "page.png")).name
                    raw = base64.b64decode(payload["data"])
                    out_dir = base_dir / title
                    out_dir.mkdir(parents=True, exist_ok=True)
                    (out_dir / filename).write_bytes(raw)
                    self.send_response(200)
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(b"ok")
                except Exception as e:
                    self.send_response(500)
                    self._send_cors()
                    self.end_headers()
                    self.wfile.write(str(e).encode("utf-8"))

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SaveHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server.server_address[1]

    def _regenerate_script(self):
        code = render_web_script(dpr=self.combo_dpr.currentData() - 2, idle_ms=self.spin_idle.value(), min_wait_ms=self.spin_min_wait.value(), start_page=self.spin_start_page.value(), port=self._server_port)
        self.script_edit.setPlainText(code)

    def _copy_to_clipboard(self):
        text = self.script_edit.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "복사 완료", "자바스크립트 코드가 클립보드에 복사되었습니다.\n\n원하는 작품의 뷰어 창에서 시작할 페이지로 이동한 뒤 F12(개발자 도구)를 열고 Console 탭에 붙여넣고(Ctrl+V) 엔터.\n(※ 만약 붙여넣기가 막히면 콘솔 창에 'allow pasting'을 입력 후 엔터.)")
