# Building and publishing h2gis-python

The package is published as one wheel per platform, each with the native
H2GIS library of that platform :

| Wheel tag | Native library |
|---|---|
| `py3-none-manylinux_2_34_x86_64` | `h2gis.so` (glibc 2.34+) |
| `py3-none-win_amd64` | `h2gis.dll` |
| `py3-none-macosx_11_0_arm64` | `h2gis.dylib` (Apple silicon) |

plus a source distribution without native library, and one conda package
per platform and Python version (3.9 to 3.13), built with
[rattler-build](https://rattler.build) from `recipe/`.

## Native libraries

They are not committed: they are downloaded into [native/](native/README.md),
one folder per platform, from the GitHub release of
[orbisgis/h2gis](https://github.com/orbisgis/h2gis/releases) named in
`native/H2GIS_RELEASE` (committed), as for the GDAL driver h2gis-gdal:
`graalvm-snapshot` (the build of master) for now, a version tag of H2GIS once
it publishes its libraries in its releases (a version tag gives the same
libraries to every build). The "CI GraalVM" workflow of H2GIS publishes them
(module `h2gis-graalvm`, Mandrel). They must implement the C API version 2 or
later (`h2gis_version()`).

```bash
python tools/update_native.py --download                      # the three platforms
python tools/update_native.py --download --current-platform   # this platform only
python tools/update_native.py --download v2.2.6               # another release
```

The script checks each library against the `SHA256SUMS` of the release,
refuses libraries with a C API older than 2 (checked for the platform it runs
on) and files over the 100 MB limit of a PyPI file, and writes the local
`native/SHA256SUMS`. To change the version, set the release in
`native/H2GIS_RELEASE`, download, test and commit.

## Continuous integration (.github/workflows/ci.yml)

On every push and pull request:

1. **tests**: the whole test suite from the checkout on Linux, Windows and
   macOS, Python 3.9 and 3.13, after
   `python tools/update_native.py --download --current-platform` (h2gis
   finds `native/<platform>/`).
2. **wheels**: for each platform, download its library, build the wheel from `native/` with
   `tools/build_wheel.py`, install it and run the test suite against the
   installed package (fails if the library of the platform is missing).
3. **sdist**: build the source distribution and check it (`twine check`).
4. **conda**: for each platform, build the conda packages of `recipe/` (one
   per Python version, `recipe/variants.yaml`) and test them (import, a
   query with the native library, `pip check`).

Publication, on a `v*` tag (it must be `v` + `__version__`), or on a manual
run (*Actions > CI > Run workflow*, input `publish`):

| `publish` | What |
|---|---|
| `testpypi` | the wheels and the sdist on [TestPyPI](https://test.pypi.org/project/h2gis/), to check a release |
| `release` (or a `v*` tag) | PyPI, the conda packages on anaconda.org, and a GitHub release `v<__version__>` with all the packages and their `SHA256SUMS` |

### One-time setup

- **PyPI trusted publishing**: in the PyPI project `h2gis` (*Manage >
  Publishing*), add a trusted publisher: owner `orbisgis`, repository
  `h2gis-python`, workflow `ci.yml`, environment `pypi`. Do the same on
  TestPyPI with the environment `testpypi` (create the project there by this
  first publication: *Your account > Publishing > Add a pending publisher*).
  Check that you are an owner of the PyPI project `h2gis`.
- **GitHub environments** `pypi`, `testpypi` and `anaconda` (*Settings >
  Environments*), optionally with required reviewers: a publication then
  waits for an approval.
- **anaconda.org**: an organization or a user (the channel), the secret
  `ANACONDA_API_KEY` (an API token with the scope *api:write*) in the
  `anaconda` environment, and the variable `ANACONDA_OWNER` if the channel is
  not `orbisgis`. Without the secret, the conda packages are only attached
  to the GitHub release.

## Releasing

1. Check the release of H2GIS in `native/H2GIS_RELEASE` (a version tag when
   H2GIS has one with its libraries), download and test (see above).
2. Update the version in `h2gis/__init__.py` (`__version__`) and `CHANGELOG.md`.
3. Push, check that the CI is green. Optionally, publish on TestPyPI first
   (manual run, `publish: testpypi`) and install it:
   `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ h2gis`.
4. Publish: a manual run with `publish: release`, or a tag
   `git tag v2.0.0 && git push --tags`. PyPI refuses a version already
   published: change `__version__` for a new publication.

## conda-forge

The package can also be proposed to conda-forge, from `recipe/recipe.yaml`,
with a pull request on
[conda-forge/staged-recipes](https://github.com/conda-forge/staged-recipes).
GraalVM is not in conda-forge: the recipe takes the native libraries built
by H2GIS (repackaged binaries), which the reviewers of conda-forge accept
case by case. For conda-forge, the source must be a release archive with
its checksum, and the libraries downloaded as sources of the recipe (the
assets of the H2GIS release), as the build has no network.

## Building locally

```bash
pip install build wheel
python tools/build_wheel.py /path/to/h2gis.so manylinux_2_34_x86_64   # -> dist/
pip install "dist/h2gis-2.0.0-py3-none-manylinux_2_34_x86_64.whl[test]"
cd /tmp && pytest /path/to/h2gis-python/test                         # tests the installed wheel
```

The conda packages, from a clone (with [rattler-build](https://rattler.build)):

```bash
python tools/update_native.py --download --current-platform
H2GIS_VERSION=2.0.0 rattler-build build --recipe recipe/ -c conda-forge   # -> output/
```

From a clone, the library of `native/` is used without building a wheel:

```bash
python tools/update_native.py --download --current-platform
pip install -e ".[test]"
pytest test/                                   # or H2GIS_TEST_LIBS=/other/h2gis.so pytest test/
```
