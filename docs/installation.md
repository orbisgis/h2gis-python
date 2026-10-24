# Installation

## Requirements

- Python 3.9+
- Shapely 2 (installed automatically), and pandas + GeoPandas for
  `read_gdf` / `read_df` / `to_h2gis`
- The native H2GIS library compiled with GraalVM
- Platforms: Linux x86-64 (glibc 2.34+), Windows x86-64, macOS on Apple silicon, build with Mandrel.

## Install the package

```bash
pip install h2gis                # from PyPI
pip install "h2gis[geopandas]"   # with pandas and GeoPandas
pip install .                    # from a clone: no native library, see DEPLOY.md
```

The native library is expected in the package:

```
h2gis/
└── lib/
    ├── h2gis.so      # Linux
    ├── h2gis.dylib   # macOS
    └── h2gis.dll     # Windows
```

## Custom library path

```python
import h2gis

conn = h2gis.connect("/data/my_db", lib_path="/custom/path/to/h2gis.so")
```

or set the `H2GIS_LIB_PATH` environment variable. All the connections of a
process share the same library; two different native libraries can't be
loaded in one process.

## Check the installation

```python
import h2gis

with h2gis.connect("mem:check") as conn:
    print(conn.execute("SELECT H2VERSION(), ST_AsText(ST_MakePoint(1, 2))").fetchone())
    print(conn.native_version)    # C API version of the native library (2 or later)
```

See [NATIVE_API.md](NATIVE_API.md) for the native library requirements.
