# H2GIS Python

A [DB-API 2.0](https://peps.python.org/pep-0249/) driver for the
[H2GIS](http://www.h2gis.org/) spatial database, with an API modelled on
[psycopg 3](https://www.psycopg.org/psycopg3/docs/). H2GIS runs embedded in
your Python process through a native library compiled with GraalVM: no Java,
no server.

```python
import h2gis
from h2gis.rows import dict_row

with h2gis.connect("/data/my_db", row_factory=dict_row) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS PLACE_NAMES(ID SERIAL, NOM VARCHAR, "
                 "THE_GEOM GEOMETRY(POINT, 4326))")
    conn.execute("INSERT INTO PLACE_NAMES VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326))",
                 [1, "Nantes", -1.55, 47.22])
    for row in conn.execute("SELECT * FROM PLACE_NAMES WHERE NOM = %s", ["Nantes"]):
        print(row["ID"], row["THE_GEOM"])          # a Shapely geometry

    # GeoPandas, CRS taken from the SRID
    gdf = h2gis.read_gdf(conn, "SELECT * FROM PLACE_NAMES")
    h2gis.to_h2gis(gdf, "PLACE_NAMES_COPY", conn, if_exists="replace")

    with conn.transaction():                         # nested blocks = savepoints
        conn.execute("DELETE FROM PLACE_NAMES WHERE ID = %s", [1])
        raise h2gis.Rollback                          # undo this block only
# committed on success, rolled back on error, then closed
```


## Documentation

* [Installation](docs/installation.md)
* [User guide](docs/DBAPI.md): connections, transactions, parameters, errors,
  pandas/GeoPandas, threads, limitations
* [Examples](docs/examples.md) and the [example](example/) folder
* [Native interface](docs/NATIVE_API.md): status of the GraalVM library and
  requested changes
* [Changelog](CHANGELOG.md), including the migration from 0.0.x

## Installation

```bash
pip install h2gis               # driver + Shapely
pip install "h2gis[geopandas]"  # + pandas and GeoPandas
```

Requirements: Python 3.9+ on Linux x86-64 (glibc 2.34+), Windows x86-64 or
macOS on Apple silicon. Each platform wheel ships the native H2GIS library
(C API 2, H2GIS 2.2.6+); set `H2GIS_LIB_PATH` or pass `lib_path=` to
`connect()` to use another one.

## Tests

```bash
pip install -e ".[test]"
pytest test/
```

From a clone, h2gis uses the native library of [native/](native/README.md).
`test/test_unit.py` needs no native library; `test/test_integration.py` runs
against the libraries listed in `H2GIS_TEST_LIBS`, or the default one, and is
skipped when none is found. Building the wheels and releasing: see
[DEPLOY.md](DEPLOY.md).

## License

LGPL 3.0. H2GIS-python is developed by the [CNRS](http://www.cnrs.fr/).
