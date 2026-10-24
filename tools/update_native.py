"""
Update the native libraries of native/ from a build of the H2GIS module
h2gis-graalvm.

    python tools/update_native.py h2gis-graalvm-all-platforms.zip
    python tools/update_native.py path/to/h2gis.so [path/to/h2gis.dll ...]
    python tools/update_native.py        # check (and sort) the libraries in native/

It works from any folder; wildcards are expanded by the script too (useful on
Windows, where the shell doesn't).

The zip is the artifact of the "CI GraalVM" workflow of orbisgis/h2gis
(h2gis.so, h2gis.dll, h2gis.dylib). Each library goes to native/<platform>/,
and native/SHA256SUMS is rewritten. A library implementing a C API older than
2 is refused when it can be loaded on this machine. Libraries bigger than
100 MB are refused: GitHub rejects such files (use Git LFS for them).
"""

import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE = os.path.join(ROOT, "native")
PLATFORMS = {"h2gis.so": "linux-x86_64", "h2gis.dll": "windows-x86_64",
             "h2gis.dylib": "macos-arm64"}
GITHUB_LIMIT = 100 * 1024 * 1024
# First bytes of an ELF (.so), PE (.dll) and Mach-O 64 bits (.dylib) file
MAGIC = {"h2gis.so": (b"\x7fELF",), "h2gis.dll": (b"MZ",),
         "h2gis.dylib": (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf")}


def check_format(path, name):
    with open(path, "rb") as f:
        head = f.read(4)
    if not any(head.startswith(m) for m in MAGIC[name]):
        sys.exit(f"{path}: not a native library ({head!r}...): a download error page, "
                 "or a Git LFS pointer?")


def c_api_version(path):
    """C API version of a library loadable here, None if it can't be checked.

    Run in a child process: two GraalVM libraries can't share a process.
    """
    code = ("import ctypes, sys\n"
            "lib = ctypes.CDLL(sys.argv[1])\n"
            "print(0 if getattr(lib, 'h2gis_version', None) is None else -1)\n")
    try:
        out = subprocess.run([sys.executable, "-c", code, path], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None  # not loadable on this machine (other OS)
    if out.stdout.strip() == "0":
        return 1
    code = ("import ctypes, sys\n"
            "lib = ctypes.CDLL(sys.argv[1])\n"
            "iso, th = ctypes.c_void_p(), ctypes.c_void_p()\n"
            "lib.graal_create_isolate(None, ctypes.byref(iso), ctypes.byref(th))\n"
            "lib.h2gis_version.argtypes = [ctypes.c_void_p]\n"
            "print(lib.h2gis_version(th))\n")
    out = subprocess.run([sys.executable, "-c", code, path], capture_output=True, text=True,
                         timeout=120)
    return int(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _expand(arg):
    """Paths matching ``arg``, relative to the current folder or to the repository."""
    for base in (os.getcwd(), ROOT):
        path = arg if os.path.isabs(arg) else os.path.join(base, arg)
        found = sorted(glob.glob(path)) if glob.has_magic(arg) else ([path] if os.path.exists(path) else [])
        if found:
            return found
    sys.exit(f"{arg}: no such file (run from the repository root, or give an absolute path)")


def collect(args, tmp):
    libs = []
    for arg in [p for a in args for p in _expand(a)]:
        if arg.endswith(".zip"):
            with zipfile.ZipFile(arg) as z:
                for name in z.namelist():
                    if os.path.basename(name) in PLATFORMS:
                        libs.append(z.extract(name, tmp))
        elif os.path.basename(arg) in PLATFORMS:
            libs.append(arg)
        else:
            sys.exit(f"{arg}: expected a zip or h2gis.so / h2gis.dll / h2gis.dylib")
    if not libs:
        sys.exit("no native library found")
    return libs


def _in_native():
    """Libraries and zips anywhere under native/ (e.g. an artifact unzipped there)."""
    found = []
    for name in list(PLATFORMS) + ["*.zip"]:
        found += glob.glob(os.path.join(NATIVE, "**", name), recursive=True)
    return sorted(set(found))


def main(args):
    stray = []
    if not args:  # check what is in native/, and sort it into the platform folders
        args = _in_native()
        if not args:
            sys.exit("native/ has no library yet\n\n" + __doc__)
        stray = [p for p in args if not p.endswith(".zip") and os.path.dirname(p) !=
                 os.path.join(NATIVE, PLATFORMS[os.path.basename(p)])]
        # a misplaced library replaces the one of its platform folder
        replaced = {os.path.join(NATIVE, PLATFORMS[os.path.basename(p)], os.path.basename(p))
                    for p in stray}
        args = [p for p in args if p not in replaced]
    with tempfile.TemporaryDirectory() as tmp:
        for lib in collect(args, tmp):
            name = os.path.basename(lib)
            check_format(lib, name)
            size = os.path.getsize(lib)
            if size >= GITHUB_LIMIT:
                sys.exit(f"{name}: {size / 1e6:.0f} MB, over the 100 MB limit of GitHub "
                         "(track native/ with Git LFS)")
            version = c_api_version(lib)
            if version is not None and version < 2:
                sys.exit(f"{name}: C API version {version}, h2gis-python needs 2 or later")
            target = os.path.join(NATIVE, PLATFORMS[name], name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if not (os.path.exists(target) and os.path.samefile(lib, target)):
                shutil.copy2(lib, target)  # else: already in native/, just check it
            checked = f"C API {version}" if version else "C API not checked on this OS"
            print(f"{os.path.relpath(target, ROOT)}: {size / 1e6:.1f} MB, {checked}")
    for path in stray:  # moved to its platform folder: drop the misplaced copy
        os.remove(path)
        print(f"{os.path.relpath(path, ROOT)}: moved to its platform folder")
    for path in (a for a in args if a.endswith(".zip") and os.path.abspath(a).startswith(NATIVE)):
        print(f"{os.path.relpath(path, ROOT)}: extracted; delete it before committing")
    lines = []
    for platform_dir in sorted(os.listdir(NATIVE)):
        folder = os.path.join(NATIVE, platform_dir)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name in PLATFORMS:
                lines.append(f"{sha256(os.path.join(folder, name))}  {platform_dir}/{name}\n")
    with open(os.path.join(NATIVE, "SHA256SUMS"), "w") as f:
        f.writelines(lines)
    print("native/SHA256SUMS updated; record the H2GIS commit in native/README.md")


if __name__ == "__main__":
    main(sys.argv[1:])