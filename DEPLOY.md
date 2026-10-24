# Building and publishing h2gis-python

The package is published as one wheel per platform, each with the native
H2GIS library of that platform :

| Wheel tag | Native library |
|---|---|
| `py3-none-manylinux_2_34_x86_64` | `h2gis.so` (glibc 2.34+) |
| `py3-none-win_amd64` | `h2gis.dll` |
| `py3-none-macosx_11_0_arm64` | `h2gis.dylib` (Apple silicon) |

plus a source distribution without native library.

## Native libraries

They are committed in [native/](native/README.md), one folder per platform,
and come from the "CI GraalVM" workflow of
[orbisgis/h2gis](https://github.com/orbisgis/h2gis/actions) (module
`h2gis-graalvm`, Mandrel), artifact `h2gis-graalvm-all-platforms`. They must
implement the C API version 2 or later (`h2gis_version()`).

To update them:

```bash
python tools/update_native.py h2gis-graalvm-all-platforms.zip
```

The script copies each library to `native/<platform>/`, refuses libraries
with a C API older than 2 (checked for the platform it runs on) and files over
the 100 MB limit of GitHub, and rewrites `native/SHA256SUMS`. Then fill in the
H2GIS commit and the run in `native/README.md` and commit.

## Continuous integration (.github/workflows/ci.yml)

On every push and pull request:

1. **tests**: the whole test suite from the checkout on Linux, Windows and
   macOS, Python 3.9 and 3.13 (h2gis finds `native/<platform>/`; the
   integration tests are skipped on a platform whose library is missing).
2. **wheels**: for each platform, build the wheel from `native/` with
   `tools/build_wheel.py`, install it and run the test suite against the
   installed package (fails if the library of the platform is missing).
3. **sdist**: build the source distribution.

On a `v*` tag, **publish** uploads the three wheels and the sdist to PyPI.

### One-time setup

**PyPI trusted publishing**: in the PyPI project `h2gis`, add a trusted
publisher: owner `orbisgis`, repository `h2gis-python`, workflow `ci.yml`,
environment `pypi`; create the `pypi` environment in the GitHub repository
settings (optionally with required reviewers).

## Releasing

1. Update the native libraries if needed (see above).
2. Update the version in `h2gis/__init__.py` (`__version__`) and `CHANGELOG.md`.
3. Push, check that the CI is green, then tag: `git tag v2.0.0 && git push --tags`.
   The publish job checks that the tag matches `__version__`.

## Building locally

```bash
pip install build wheel
python tools/build_wheel.py /path/to/h2gis.so manylinux_2_34_x86_64   # -> dist/
pip install "dist/h2gis-2.0.0-py3-none-manylinux_2_34_x86_64.whl[test]"
cd /tmp && pytest /path/to/h2gis-python/test                         # tests the installed wheel
```

From a clone, the library of `native/` is used without building a wheel:

```bash
pip install -e ".[test]"
pytest test/                                   # or H2GIS_TEST_LIBS=/other/h2gis.so pytest test/
```
