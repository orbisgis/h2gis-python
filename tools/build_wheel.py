"""
Build the wheel of one platform with its native library.

The H2GIS native library is a GraalVM shared library, not a Python
extension, so the wheel is pure Python ("py3-none") except for the platform
tag, set from the library given:

    python tools/build_wheel.py path/to/h2gis.so  manylinux_2_34_x86_64
    python tools/build_wheel.py path/to/h2gis.dll win_amd64
    python tools/build_wheel.py path/to/h2gis.dylib macosx_11_0_arm64

The wheel is written to dist/. h2gis/lib/ is emptied before and after.
"""

import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_DIR = os.path.join(ROOT, "h2gis", "lib")
NAMES = {".so": "h2gis.so", ".dll": "h2gis.dll", ".dylib": "h2gis.dylib"}


def clean_lib_dir():
    shutil.rmtree(LIB_DIR, ignore_errors=True)
    shutil.rmtree(os.path.join(ROOT, "build"), ignore_errors=True)


def main(lib_path: str, platform_tag: str) -> str:
    ext = os.path.splitext(lib_path)[1]
    if ext not in NAMES:
        sys.exit(f"unexpected native library {lib_path!r} (.so, .dll or .dylib)")
    clean_lib_dir()
    os.makedirs(LIB_DIR)
    shutil.copy2(lib_path, os.path.join(LIB_DIR, NAMES[ext]))
    try:
        out = os.path.join(ROOT, "dist", f"tmp-{platform_tag}")
        shutil.rmtree(out, ignore_errors=True)
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", out, ROOT],
                       check=True)
        (wheel,) = glob.glob(os.path.join(out, "*-py3-none-any.whl"))
        subprocess.run([sys.executable, "-m", "wheel", "tags", "--remove",
                        "--platform-tag", platform_tag, wheel], check=True)
        (tagged,) = glob.glob(os.path.join(out, "*.whl"))
        final = os.path.join(ROOT, "dist", os.path.basename(tagged))
        os.replace(tagged, final)
        shutil.rmtree(out)
        print(final)
        return final
    finally:
        clean_lib_dir()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
