from pathlib import Path
import shutil

from PySide6.QtWidgets import QMainWindow, QTabWidget
from shiboken6 import isValid

from core.paths import DIR_TMP, ensure_app_dirs
from core.settings import load_app_settings, save_app_settings
from ui.tabs.convert import ConvertTab
from ui.tabs.web_script import WebScriptTab


class MainWindow(QMainWindow):
    def __init__(self, settings_path: Path):
        super().__init__()
        self.settings_path = settings_path
        self.setWindowTitle("Mine BookWalker Downloader")
        self.resize(1140, 780)

        ensure_app_dirs()
        self.app_settings = load_app_settings(self.settings_path)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab_convert = ConvertTab(self.app_settings)
        self.tab_web = WebScriptTab(self.app_settings)

        self.tab_convert.settingsChanged.connect(self._save_settings)
        self.tab_web.settingsChanged.connect(self._save_settings)

        self.tabs.addTab(self.tab_convert, "변환")
        self.tabs.addTab(self.tab_web, "다운로더")

    def _save_settings(self):
        self.app_settings.update(self.tab_convert.collect_settings())
        self.app_settings.update(self.tab_web.collect_settings())
        save_app_settings(self.settings_path, self.app_settings)

    def closeEvent(self, event):
        worker = getattr(self.tab_convert, "_analysis_worker", None)
        if worker is not None:
            try:
                if isValid(worker):
                    worker.cancel()
                    worker.wait(1000)
            except RuntimeError:
                pass
            self.tab_convert._analysis_worker = None
        shutil.rmtree(DIR_TMP / "preview", ignore_errors=True)
        self._save_settings()
        super().closeEvent(event)
