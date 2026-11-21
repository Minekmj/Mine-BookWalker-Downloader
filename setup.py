import os
import shutil
import sys
from pathlib import Path
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

compile_args = ["/O2"] if sys.platform == "win32" else ["-O3"]


class CleanBuildExt(build_ext):
    def get_ext_filename(self, ext_name):
        parts = ext_name.split(".")
        return os.path.join(*parts) + (".pyd" if sys.platform == "win32" else ".so")

    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        build_dir = root / "build"
        if build_dir.is_dir():
            shutil.rmtree(build_dir, ignore_errors=True)
        c_dir = root / "C"
        if c_dir.is_dir():
            for pattern in ("*.lib", "*.exp", "*.obj"):
                for item in c_dir.glob(pattern):
                    item.unlink(missing_ok=True)


extensions = [
    Extension("C.c_margins", sources=["C/c_margins.c"], extra_compile_args=compile_args),
    Extension("C.c_header", sources=["C/c_header.c"], extra_compile_args=compile_args),
    Extension("C.c_layout", sources=["C/c_layout.c"], extra_compile_args=compile_args),
    Extension("C.c_illust", sources=["C/c_illust.c"], extra_compile_args=compile_args),
]

setup(
    name="unbook_c_extensions",
    version="2.0",
    description="Modular C extensions for novel page layout and image analysis",
    ext_modules=extensions,
    cmdclass={"build_ext": CleanBuildExt},
)