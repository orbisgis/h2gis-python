"""
Update the native libraries of native/ from a build of the H2GIS module
h2gis-graalvm.

    python tools/update_native.py --download          # release of native/H2GIS_RELEASE
    python tools/update_native.py --download v2.2.6   # another release
    python tools/update_native.py --download --current-platform   # this platform only
    python tools/update_native.py h2gis-graalvm-all-platforms.zip
    python tools/update_native.py path/to/h2gis.so [path/to/h2gis.dll ...]
    python tools/update_native.py        # check (and sort) the libraries in native/

--download takes the libraries of a GitHub release of orbisgis/H2GIS, published
by its "CI GraalVM" workflow (h2gis-linux-x86_64.so, h2gis-windows-x86_64.dll,
h2gis-macos-arm64.dylib), and checks them against the SHA256SUMS of the
release. The release is read from native/H2GIS_RELEASE (committed):
graalvm-snapshot (the build of master), or a version tag of H2GIS. Another
release can be given on the command line to test it. The libraries are not
committed (.gitignore).

It works from any folder; wildcards are expanded by the script too (useful on
Windows, where the shell doesn't).

The zip is the artifact of the "CI GraalVM" workflow of orbisgis/h2gis
(h2gis.so, h2gis.dll, h2gis.dylib). Each library goes to native/<platform>/,
and native/SHA256SUMS is rewritten. A library implementing a C API older than
2 is refused when it can be loaded on this machine. Libraries bigger than
100 MB are refused: PyPI rejects such files (and GitHub too).
"""

import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NATIVE = os.path.join(ROOT, "native")
PLATFORMS = {"h2gis.so": "linux-x86_64", "h2gis.dll": "windows-x86_64",
             "h2gis.dylib": "macos-arm64"}
GITHUB_LIMIT = 100 * 1024 * 1024  # also the default limit of a PyPI file
RELEASE_FILE = os.path.join(NATIVE, "H2GIS_RELEASE")
RELEASES_URL = "https://github.com/orbisgis/H2GIS/releases/download"
# Name of each library in the releases of H2GIS
RELEASE_ASSETS = {"h2gis.so": "h2gis-linux-x86_64.so", "h2gis.dll": "h2gis-windows-x86_64.dll",
                  "h2gis.dylib": "h2gis-macos-arm64.dylib"}
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


def configured_release():
    """The release of native/H2GIS_RELEASE: its first line that is not a comment."""
    name = os.path.relpath(RELEASE_FILE, ROOT)
    try:
        with open(RELEASE_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except OSError:
        pass
    sys.exit(f"{name}: missing or empty (graalvm-snapshot or a version tag of H2GIS)")


def current_library_name():
    """h2gis.so, h2gis.dll or h2gis.dylib, for this machine."""
    return {"win32": "h2gis.dll", "darwin": "h2gis.dylib"}.get(sys.platform, "h2gis.so")


def _fetch(url, path, hint=None):
    try:
        with urllib.request.urlopen(url) as response, open(path, "wb") as out:
            shutil.copyfileobj(response, out)
    except Exception as exc:
        sys.exit(f"cannot download {url}: {exc}" + (f"; {hint}" if hint else ""))


def download(release, names, tmp):
    """Download the libraries of a release of H2GIS, checked against its SHA256SUMS."""
    base = f"{RELEASES_URL}/{release}"
    sums_path = os.path.join(tmp, "SHA256SUMS")
    _fetch(f"{base}/SHA256SUMS", sums_path, f"no native libraries published in the H2GIS "
           f"release {release}: see https://github.com/orbisgis/h2gis/releases")
    expected = {}
    with open(sums_path) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                expected[parts[1].lstrip("*")] = parts[0]
    libs = []
    for name in names:
        asset = RELEASE_ASSETS[name]
        if asset not in expected:
            sys.exit(f"{asset} is not in {base}/SHA256SUMS")
        folder = os.path.join(tmp, PLATFORMS[name])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        print(f"downloading {base}/{asset}")
        _fetch(f"{base}/{asset}", path)
        if sha256(path) != expected[asset]:
            sys.exit(f"{asset}: checksum different from {base}/SHA256SUMS")
        libs.append(path)
    return libs


def _in_native():
    """Libraries and zips anywhere under native/ (e.g. an artifact unzipped there)."""
    found = []
    for name in list(PLATFORMS) + ["*.zip"]:
        found += glob.glob(os.path.join(NATIVE, "**", name), recursive=True)
    return sorted(set(found))


def main(args):
    if args and args[0] == "--download":
        options = args[1:]
        current = "--current-platform" in options
        rest = [a for a in options if a != "--current-platform"]
        if len(rest) > 1 or any(a.startswith("-") for a in rest):
            sys.exit(__doc__)
        release = rest[0] if rest else configured_release()
        if rest:
            print(f"release {release} given on the command line, instead of native/H2GIS_RELEASE")
        names = [current_library_name()] if current else list(PLATFORMS)
        with tempfile.TemporaryDirectory() as tmp:
            install(download(release, names, tmp), [])
        print(f"native libraries of the H2GIS release {release}")
        return
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
        install(collect(args, tmp), stray)
    for path in (a for a in args if a.endswith(".zip") and os.path.abspath(a).startswith(NATIVE)):
        print(f"{os.path.relpath(path, ROOT)}: extracted; delete it before committing")


def install(libs, stray):
    """Check the libraries, copy them to native/<platform>/ and write SHA256SUMS."""
    for lib in libs:
        name = os.path.basename(lib)
        check_format(lib, name)
        size = os.path.getsize(lib)
        if size >= GITHUB_LIMIT:
            sys.exit(f"{name}: {size / 1e6:.0f} MB, over the 100 MB limit of a PyPI "
                     "file: the wheel could not be published")
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
    lines = []
    for platform_dir in sorted(os.listdir(NATIVE)):
        folder = os.path.join(NATIVE, platform_dir)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name in PLATFORMS:
                lines.append(f"{sha256(os.path.join(folder, name))}  {platform_dir}/{name}\n")
    with open(os.path.join(NATIVE, "SHA256SUMS"), "w") as f:
        f.writelines(lines)
    print("native/SHA256SUMS updated")


if __name__ == "__main__":
    main(sys.argv[1:])