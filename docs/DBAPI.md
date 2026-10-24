# DB-API 2.0 driver

`h2gis` is a [PEP 249](https://peps.python.org/pep-0249/) driver whose API
follows the same schema as [psycopg 3](https://www.psycopg.org/psycopg3/docs/).

Here an example to use H2GIS
```python
import h2gis
from h2gis.rows import dict_row
from shapely import Point

with h2gis.connect("/data/my_db", row_factory=dict_row) as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS PLACE_NAMES(ID INT PRIMARY KEY, NOM VARCHAR, "
                 "THE_GEOM GEOMETRY(POINT, 4326))")
    conn.execute("INSERT INTO PLACE_NAMES VALUES (%s, %s, %s)",
                 [1, "Nantes", h2gis.Geometry(Point(-1.55, 47.22), srid=4326)])
    for row in conn.execute("SELECT * FROM PLACE_NAMES WHERE ID = %s", [1]):
        print(row["NOM"], row["THE_GEOM"].wkt)
```

## Connections

`h2gis.connect(conninfo="mem:", user="sa", password="", *, autocommit=False,
row_factory=None, prepare=None, lib_path=None)`

* `conninfo` is what follows `jdbc:h2:`: `/data/my_db`, `./my_db`,
  `mem:test`, URL options after `;` (`/data/db;AUTO_SERVER=TRUE`). A relative
  path without `./` is accepted and a trailing `.mv.db` is removed.
* The native library is `$H2GIS_LIB_PATH`, `lib_path=`, or the bundled
  `h2gis/lib/h2gis.<so|dll|dylib>`. One GraalVM isolate is shared by all the
  connections of a process.


## Queries and parameters

* Placeholders are `%s` and `%(name)s` (`%b`/`%t` accepted), never `?`.
* With parameters, a literal `%` is written `%%` (also inside strings, like
  psycopg). Without parameters the query is sent as is.
* Parameters are bound natively (JDBC `PreparedStatement`). With
  `prepare=False` (on `connect()` or `execute()`) they are inlined as escaped
  SQL literals instead, like psycopg's `ClientCursor`. Both are safe against
  SQL injection.
* A query string can contain several statements when no parameters are passed.

**DataTypes mapping**

| Python | H2 |
|---|---|
| `None` | `NULL` |
| `bool`, `int`, `float`, `Decimal`, `str`, `bytes` | BOOLEAN, BIGINT (NUMERIC if larger), DOUBLE, NUMERIC, VARCHAR, VARBINARY |
| `date`, `time`, `datetime` (naive / aware) | DATE, TIME, TIMESTAMP / TIMESTAMP WITH TIME ZONE |
| `uuid.UUID` | UUID |
| `h2gis.Json(obj)` | JSON (`json.dumps(obj)`) |
| Shapely geometry | GEOMETRY (EWKB, keeps `shapely.get_srid()`) |
| `h2gis.Geometry(geom, srid=4326)` | GEOMETRY with that SRID |
| `list`, `tuple` | ARRAY |
| numpy scalars | their Python value |

From H2GIS, results come back as Python ints, floats, bools, strings, `bytes`,
`decimal.Decimal`, `date`/`time`/`datetime` (aware for
WITH TIME ZONE types), `uuid.UUID`, parsed JSON (`json.loads`) and Shapely
geometries (with their SRID). SQL NULL is always `None`. ARRAY and INTERVAL
values come back as strings.

Custom types:

You are welcome to add custom types from Python.

```python
h2gis.adapters.register_dumper(MyPoint, lambda p: shapely.Point(p.x, p.y))  # global
conn.adapters.register_loader("CHARACTER VARYING", str.strip)                # one connection
```

### Parametrised SQL

```python
from h2gis import sql
q = sql.SQL("SELECT {} FROM {} WHERE ID = %s").format(
    sql.Identifier("NOM"), sql.Identifier("PUBLIC", "PLACE_NAMES"))
conn.execute(q, [1])
```

`sql.Identifier` always quotes: H2 upper-cases *unquoted* names, so the table
created by `CREATE TABLE place_names` is `sql.Identifier("PLACE_NAMES")`.

## Cursors

`execute()`, `executemany()`, `fetchone()`, `fetchmany()`, `fetchall()`,
iteration, `description` (7-items `Column` with `.name`, `.type_code`,
`.type_name`), `rowcount`, `rownumber`, `arraysize`, `close()`.

* `cur.stream(query, params, size=10000)` reads big results in batches
  (`h2gis_fetch_batch`), so they never sit entirely in memory.
* `cur.fetch_columns()` returns `{name: [values]}` without building rows.

Row factories (`h2gis.rows`): `tuple_row` (default), `dict_row`,
`namedtuple_row`, `class_row(cls)`, `args_row(func)`, `kwargs_row(func)`.

## Errors

The H2 error code uses a specific
class, as `psycopg.errors` does with the SQLSTATE:

```python
try:
    conn.execute("INSERT INTO PLACE_NAMES VALUES (%s, %s, NULL)", [1, "doublon"])
except h2gis.errors.UniqueViolation as e:
    print(e.h2_code, e.sqlstate)   # 23505 23505
```
Bellow the list of errors : 

`UndefinedTable`, `UndefinedColumn`, `UndefinedFunction`,
`DuplicateTable`, `DuplicateColumn`, `SyntaxError`, `UniqueViolation`,
`ForeignKeyViolation`, `NotNullViolation`, `CheckViolation`,
`InvalidTextRepresentation`, `NumericValueOutOfRange`, `DivisionByZero`,
`StringDataRightTruncation`, `LockNotAvailable`, `SerializationFailure`,
`DatabaseAlreadyOpen`, `DatabaseNotFound`, `FetchError`.

## pandas and GeoPandas

H2GIS  can be easily linked to pandas or GeoPandas

```python
gdf = h2gis.read_gdf(conn, "SELECT * FROM PLACE_NAMES WHERE ST_Intersects(THE_GEOM, %s)", [zone])
df = h2gis.read_df(conn, "SELECT NOM, POP FROM COMMUNES")
for chunk in h2gis.read_gdf(conn, "SELECT * FROM BATIMENTS", chunksize=100_000):
    ...
h2gis.to_h2gis(gdf, "copy_place_names", conn, if_exists="replace", spatial_index=True)
```

* `read_gdf` picks the first GEOMETRY column (or `geometry=`), and the CRS
  from the SRID of the geometries (`EPSG:<srid>`, or `crs=`). Other geometry
  columns become GeoSeries. Empty results keep their columns.
* `to_h2gis` creates the table (`if_exists="fail" | "replace" | "append"`),
  maps the dtypes (geometry columns become `GEOMETRY(<type>, <srid>)`), turns
  NaN/NaT/None into NULL and inserts in multi-row INSERTs of `chunksize` rows.
  Plain table and column names are upper-cased like unquoted names in H2
  (`"place_names"` -> `PLACE_NAMES`, `geometry` -> `GEOMETRY`); pass `sql.Identifier` to
  keep the case.

## Threads

`h2gis.threadsafety == 2`: threads can share the module and connections. Each
Python thread is attached to the GraalVM isolate on first use and detached when
it ends; calls on a connection are serialized by a lock.

## Native library

The driver needs a native library implementing the H2GIS C API version 2 or
later: see [NATIVE_API.md](NATIVE_API.md).
