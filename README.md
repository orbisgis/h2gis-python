# H2GIS Python

This is a python package that allows to manipulate H2GIS spatial database using a GraalVM-compiled native library and a C interface.

## Main points

- [Installation](#Installation): Installation and setup instructions.
- [H2GIS class](#H2GIS-Class): Detailed documentation for the `H2GIS` class.
- [Example](#Usage-Examples): Example usage of the library.

If you want information about h2gis you can go to the [h2gis website](http://www.h2gis.org/).

# Installation

## Requirements

- Python 3.7+
- Native H2GIS shared library compiled with GraalVM
- Supported platforms: Linux, Windows, macOS

## Install the Python Package

```bash
pip install .
```

Ensure the native library file is present in the following structure:

```
h2gis/
├── lib/
│   ├── h2gis.so      # Linux
│   ├── h2gis.dylib   # macOS
│   └── h2gis.dll     # Windows
```



## Custom Library Path

You can specify a custom path to the native library:

```python
from h2gis import H2GIS

db = H2GIS(lib_path="/custom/path/to/h2gis.so")


# H2GIS Class

## Overview

`H2GIS` is a Python class that wraps a native shared library compiled with GraalVM. It provides access to an embedded H2GIS database using GraalVM isolate and thread objects.

## Constructor

```python
H2GIS(lib_path=None)
```

- `lib_path`: Optional path to the `.so`, `.dll`, or `.dylib` file. If not provided, a default path is used based on the current OS.

## Methods

### `connect(db_file: str, username="sa", password="")`

Connect to a local H2GIS database file.

### `execute(sql: str) -> int`

Execute an `INSERT`, `UPDATE`, or `DELETE` SQL statement.

### `fetch(sql: str) -> list[str]`

Execute a `SELECT` SQL query and return results as a list of strings (one per row).

### `close()`

Close the active database connection.

### `__del__()`

Destructor that automatically tears down the GraalVM isolate and closes any connection.

# H2GIS Class

## Overview

`H2GIS` is a Python class that wraps a native shared library compiled with GraalVM. It provides access to an embedded H2GIS database using GraalVM isolate and thread objects.

## Constructor

```python
H2GIS(lib_path=None)
```

- `lib_path`: Optional path to the `.so`, `.dll`, or `.dylib` file. If not provided, a default path is used based on the current OS.

## Methods

### `connect(db_file: str, username="sa", password="")`

Connect to a local H2GIS database file.

### `execute(sql: str) -> int`

Execute an `INSERT`, `UPDATE`, or `DELETE` SQL statement.

### `commit() -> int`

Commit the current transaction by executing `COMMIT;`.

### `rollback() -> int`

Rollback the current transaction by executing `ROLLBACK;`.

### `fetch(query: str, row_index: int = 1, stringformat="utf-8") -> dict[str, list]`

Execute a `SELECT` SQL query and return all result rows as a typed dictionary. Each key is a column name, and each value is a list of column values.

### `parse_string_buffer(buf: bytes, num_rows: int) -> list[str | None]`

Parse a buffer of length-prefixed UTF-8 strings or null entries.

### `parse_geometry_buffer(buf: bytes, num_rows: int) -> List[Optional[BaseGeometry]]`

Parse a buffer of WKB geometry entries and return a list of Shapely geometry objects or `None`.

### `deserialize_resultset_buffer(buf: bytes) -> dict[str, list]`

Deserialize the binary buffer returned by the native `fetch_all` function into a dictionary of columns with typed values.

### `isConnected() -> bool`

Return `True` if a database connection is currently active and responsive.

### `ping() -> bool`

Check if the database connection is alive by executing a test query.

### `close()`

Close the current database connection but leave the isolate active.

### `deleteAndClose()`

Delete the database file (if applicable) and close the connection.


# Usage Examples

## Basic Example

```python

from h2gis import H2GIS
import geopandas as gpd
import pandas as pd
from shapely.wkt import loads as wkt_loads
import json
import matplotlib.pyplot as plt  # Import matplotlib
import ast

# Connexion and data import
h2gis = H2GIS("/mydb/path/dbName", "sa", "sa")
h2gis.execute("""
        DROP TABLE IF EXISTS LIEUX;
        CREATE TABLE LIEUX (
            ID INT PRIMARY KEY AUTO_INCREMENT,
            NOM VARCHAR(255),
            DESCRIPTION VARCHAR(255),
            THE_GEOM GEOMETRY(GEOMETRY)
        );
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Paris', 'Capitale de la France', ST_GeomFromText('POINT(2.3522 48.8566)', 4326));
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Lyon', 'Ville gastronomique', ST_GeomFromText('POINT(4.8357 45.7640)', 4326));
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Marseille', 'Port méditerranéen', ST_GeomFromText('POINT(5.3698 43.2965)', 4326));
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Englobant', 'Géométrie englobante', ST_GeomFromText('POLYGON((
        -4.72 48.42,
        -1.35 47.23,
        0.88 47.90,
        2.35 48.86,
        4.08 49.33,
        5.70 49.00,
        6.65 48.16,
        7.75 48.58,
        7.27 47.50,
        6.75 46.15,
        6.00 45.45,
        4.90 44.50,
        4.20 43.80,
        5.3698 43.2965,
        3.50 43.00,
        2.50 42.50,
        0.50 42.80,
        -1.00 43.40,
        -1.80 44.50,
        -2.50 45.80,
        -2.90 46.80,
        -3.50 47.80,
        -4.72 48.42
    ))', 4326)
);
""")

# Fetch the select query
fetch = h2gis.fetch("SELECT NOM, DESCRIPTION, THE_GEOM as geometry FROM LIEUX;")
print(fetch)

# Convert as dataframe
gdf = gpd.GeoDataFrame(fetch, geometry="GEOMETRY", crs="EPSG:4326")
print(gdf)

# Gest distance between first two points
if len(gdf) >= 2:
    paris_geom = gdf[gdf['NOM'] == 'Paris'].geometry.iloc[0]
    lyon_geom = gdf[gdf['NOM'] == 'Lyon'].geometry.iloc[0]
    dist_paris_lyon = paris_geom.distance(lyon_geom) * 111319.9

    print(f"Distance in meters between poit 1 and 2: {dist_paris_lyon:.2f} m")
else:
    print("2 geometries needed to calculate a distance")

print("connected : ", h2gis.isConnected())
h2gis.close()

# Display data
gdf.plot(edgecolor='black', figsize=(10, 8))
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.show()
```

## Custom Native Library Path

```python
db = H2GIS(lib_path="/custom/path/h2gis.so")
```

## Notes
- By default, the native `.so`, `.dll` are already included in the package, in the `lib` folder.
