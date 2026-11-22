from ui.workers.options import EpubOnlyOptions
from PySide6.QtCore import QThread, Signal
from core.export.epub.styles import EpubDesignConfig
from core.export.exporters import export_light_novel, load_ocr_backup
from core.config.paths import DIR_OUT


class EpubOnlyWorker(QThread):
    log = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, opts: EpubOnlyOptions):
        super().__init__()
        self.opts = opts

    def run(self):
        try:
            if self.opts.source_path.suffix.lower() != ".json":
                raise RuntimeError("현재 EPUB 단독 생성은 OCR 백업 JSON을 지원합니다.")
            entries = load_ocr_backup(self.opts.source_path)
            if not entries:
                raise RuntimeError("불러온 파일에 변환할 페이지가 없습니다.")
            design = EpubDesignConfig.from_dict(self.opts.epub_design or {})
            design.writing_mode = self.opts.writing_mode
            design.scene_break_style = self.opts.scene_break_style
            epub, chapters = export_light_novel(DIR_OUT, self.opts.book_title, entries, self.opts.epub_path, False, True, design)
            self.finished_ok.emit(f"EPUB 생성 완료\n{epub}\n목차 {len(chapters)}개")
        except Exception as exc:
            self.failed.emit(str(exc))
