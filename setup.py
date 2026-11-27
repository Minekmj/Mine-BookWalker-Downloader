import os
import shutil
import sys
from pathlib import Path
from setuptools import Extension, setup
from setuptools.command.build_ext import build_ext

if sys.platform == "win32":
    compile_args = ["/O2", "/arch:AVX2"]
else:
    compile_args = ["-O3", "-march=native"]


class CleanBuildExt(build_ext):
    def finalize_options(self):
        super().finalize_options()
        self.inplace = 1

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
            for pattern in ("*.lib", "*.exp", "*.obj", "*.o"):
                for item in c_dir.glob(pattern):
                    item.unlink(missing_ok=True)


common_deps = ["C/_common.h"]

extensions = [
    Extension("C.c_margins", sources=["C/c_margins.c"], depends=common_deps, extra_compile_args=compile_args),
    Extension("C.c_header", sources=["C/c_header.c"], depends=common_deps, extra_compile_args=compile_args),
    Extension("C.c_layout", sources=["C/c_layout.c"], depends=common_deps, extra_compile_args=compile_args),
    Extension("C.c_illust", sources=["C/c_illust.c"], depends=common_deps, extra_compile_args=compile_args),
]

setup(
    name="unbook_c_extensions",
    version="2.0",
    description="Modular C extensions for novel page layout and image analysis",
    ext_modules=extensions,
    cmdclass={"build_ext": CleanBuildExt},
)