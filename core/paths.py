from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
OUT_ROOT = ROOT_DIR / "out"

DIR_OUT = OUT_ROOT / "out"
DIR_EPUB = OUT_ROOT / "epub"
DIR_BACK_OCR = OUT_ROOT / "back" / "ocr"
OUT_IMG = ROOT_DIR / "out" / "download"
DIR_TMP = ROOT_DIR / "tmp"


def ensure_app_dirs():
    for d in (DIR_OUT, DIR_EPUB, DIR_BACK_OCR, OUT_IMG, DIR_TMP):
        d.mkdir(parents=True, exist_ok=True)
