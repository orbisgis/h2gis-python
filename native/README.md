# Native libraries

The H2GIS native library of each platform, built from the
[`h2gis-graalvm`](https://github.com/orbisgis/h2gis/tree/master/h2gis-graalvm)
module of H2GIS with Mandrel. Each wheel ships the library of its platform;
from a clone of this repository, `h2gis.connect()` and the tests find them here.

| Folder | File | Wheel platform tag |
|---|---|---|
| `linux-x86_64/` | `h2gis.so` | `manylinux_2_34_x86_64` (glibc 2.34+) |
| `windows-x86_64/` | `h2gis.dll` | `win_amd64` |
| `macos-arm64/` | `h2gis.dylib` | `macosx_11_0_arm64` |


## Updating

1. Download the artifact `h2gis-graalvm-all-platforms` of a "CI GraalVM" run of
   [orbisgis/h2gis](https://github.com/orbisgis/h2gis/actions).
2. `python tools/update_native.py h2gis-graalvm-all-platforms.zip`
   (copies the libraries here, refuses C API < 2 and files over 100 MB, writes
   `SHA256SUMS`).
3. Fill in the table above, commit, and check that the CI is green.

