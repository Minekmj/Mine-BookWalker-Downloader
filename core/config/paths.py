import ctypes
import os
import shutil

from path_clean import get_app_dir

ROOT_DIR = get_app_dir()
OUT_ROOT = ROOT_DIR / "out"

DIR_OUT = OUT_ROOT / "out"
DIR_EPUB = OUT_ROOT / "epub"
DIR_BACK_OCR = OUT_ROOT / "back" / "ocr"
OUT_IMG = ROOT_DIR / "out" / "download"
DIR_TMP = ROOT_DIR / "tmp"
SESSION_TMP = DIR_TMP / f"proc_{os.getpid()}"


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259
            return False
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def ensure_app_dirs():
    for d in (DIR_OUT, DIR_EPUB, DIR_BACK_OCR, OUT_IMG, DIR_TMP, SESSION_TMP):
        d.mkdir(parents=True, exist_ok=True)


def cleanup_stale_tmp():
    if not DIR_TMP.is_dir():
        return
    for entry in DIR_TMP.iterdir():
        if entry == SESSION_TMP:
            continue
        if entry.is_dir() and entry.name.startswith("proc_"):
            try:
                pid = int(entry.name.split("_", 1)[1])
            except (IndexError, ValueError):
                pid = -1
            if _is_pid_alive(pid):
                continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)


def cleanup_session_tmp():
    shutil.rmtree(SESSION_TMP, ignore_errors=True)
