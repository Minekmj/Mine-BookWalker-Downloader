import sys
from pathlib import Path
from typing import Union


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_dir() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parent


def app_path(*parts: Union[str, Path]) -> Path:
    return get_app_dir().joinpath(*parts)


def resource_path(*parts: Union[str, Path]) -> Path:
    return get_resource_dir().joinpath(*parts)


def clean_path(path: Union[str, Path]) -> Path:
    raw = str(path).strip().strip('"').strip("'")
    return Path(raw).expanduser().resolve()
