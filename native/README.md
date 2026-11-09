# Native libraries

The H2GIS native library of each platform, built from the
[`h2gis-graalvm`](https://github.com/orbisgis/h2gis/tree/master/h2gis-graalvm)
module of H2GIS with Mandrel, and published by the "CI GraalVM" workflow of
H2GIS in its [GitHub releases](https://github.com/orbisgis/h2gis/releases).
Each wheel ships the library of its platform; from a clone of this
repository, `h2gis.connect()` and the tests find them here.

The libraries are not committed: download them once after cloning, from the
release of H2GIS named in [`H2GIS_RELEASE`](H2GIS_RELEASE): `graalvm-snapshot`
(the build of master, as for the GDAL driver h2gis-gdal) for now, a version tag
such as `v2.2.6` once H2GIS publishes its libraries in its releases:

```bash
python tools/update_native.py --download                      # the three platforms
python tools/update_native.py --download --current-platform   # this platform only
```

The script checks each library against the `SHA256SUMS` of the release, its
format, its C API version (2 or later, on the platform it runs on) and its
size (under the 100 MB limit of a PyPI file), then writes the local
`SHA256SUMS`.

| Folder | File | Release asset | Wheel platform tag |
|---|---|---|---|
| `linux-x86_64/` | `h2gis.so` | `h2gis-linux-x86_64.so` | `manylinux_2_34_x86_64` (glibc 2.34+) |
| `windows-x86_64/` | `h2gis.dll` | `h2gis-windows-x86_64.dll` | `win_amd64` |
| `macos-arm64/` | `h2gis.dylib` | `h2gis-macos-arm64.dylib` | `macosx_11_0_arm64` |

## Changing the version of the libraries

1. Set the release of H2GIS in `H2GIS_RELEASE`. A version tag gives the same
   libraries to every build of a version of h2gis-python; `graalvm-snapshot`
   changes with each build of master. Another release can be tested with
   `python tools/update_native.py --download v2.2.6`.
2. `python tools/update_native.py --download` and run the tests.
3. Commit `H2GIS_RELEASE`.

A library that is not published (a local build of H2GIS, or the artifact
`h2gis-graalvm-all-platforms` of a CI run) is installed the same way, with
the same checks: `python tools/update_native.py h2gis-graalvm-all-platforms.zip`.
