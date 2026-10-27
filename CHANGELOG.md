# Changelog

## 2.0.0

A rewrite: `h2gis` is now a DB-API 2.0 (PEP 249) driver with an API closed
to psycopg 3 syntax. **The `H2GIS` class of the 0.0.x versions is removed.**

### Added

- `h2gis.connect()`, `Connection`, `Cursor`: `conn.execute()` returning the
  cursor, `fetchone/fetchmany/fetchall`, iteration, `description`, `rowcount`,
  `executemany()`, `cursor.stream()` for big results.
- Transactions: not in autocommit by default, `commit()`/`rollback()`,
  `autocommit` attribute, `with conn:` (commit or rollback, then close),
  nested `conn.transaction()` blocks with savepoints, `h2gis.Rollback`.
- Parameters `%s` / `%(name)s`, bound natively (prepared statements), or as
  escaped literals with `prepare=False`; `executemany()` uses native batches.
- Adaptation of Shapely geometries (EWKB, SRID kept), dates and times (time
  zones included), UUID, exact Decimal, bytes, JSON (`h2gis.Json`), lists;
  custom dumpers and loaders (`h2gis.adapters`). SQL NULL is always `None`.
- Row factories: `tuple_row`, `dict_row`, `namedtuple_row`, `class_row`...
- `h2gis.sql`: `SQL`, `Identifier`, `Literal`, `Placeholder`.
- PEP 249 exception hierarchy plus specific classes chosen from the H2 error
  code (`UndefinedTable`, `UniqueViolation`, `DatabaseAlreadyOpen`...).
- pandas / GeoPandas: `read_df`, `read_gdf` (CRS from the SRID, chunked
  reading), `to_h2gis` (table creation, geometry type and SRID, spatial index).
- Thread support (`threadsafety = 2`).
- Requires a native library implementing the H2GIS C API 2 (H2GIS 2.2.6+),
  built with Mandrel; older libraries are refused. See
  [docs/NATIVE_API.md](docs/NATIVE_API.md).
- One wheel per platform (Linux x86-64, Windows x86-64, macOS arm64) with its
  native library; the libraries are kept in `native/` (updated with
  `tools/update_native.py`); `pyproject.toml` replaces `setup.py`; GitHub
  Actions CI (tests on the three platforms, wheels, PyPI publishing on tags).

### Removed

- The `H2GIS` class and its methods.

### Migration from 0.0.x

| 0.0.x | 2.0 |
|---|---|
| `db = H2GIS("/path/db", "sa", "")` | `conn = h2gis.connect("/path/db", "sa", "")` |
| `H2GIS(lib_path=...)` | `h2gis.connect(..., lib_path=...)` or `H2GIS_LIB_PATH` |
| `db.execute(sql)` | `conn.execute(sql)`; parameters: `conn.execute(sql, [a, b])` with `%s` |
| `db.fetch(sql)` → `{column: [values]}` | `conn.execute(sql).fetchall()` → rows, or `cur.fetch_columns()` → `{column: [values]}` |
| `gpd.GeoDataFrame(db.fetch(sql), geometry="THE_GEOM", crs=...)` | `h2gis.read_gdf(conn, sql)` |
| `db.commit()`, `db.rollback()` | same, or `with conn.transaction():` |
| `db.isConnected()`, `db.ping()` | `not conn.closed` |
| `db.close()` | `conn.close()` or `with h2gis.connect(...) as conn:` |
| `db.deleteAndClose()` | `conn.delete_database()` |
| `RuntimeError` | `h2gis.Error` subclasses |

Behaviour changes to watch:

- Statements run in a transaction: call `conn.commit()`, use `with conn:`, or
  connect with `autocommit=True` to get the 0.0.x behaviour.
- A relative database path no longer needs `./`, and a trailing `.mv.db` is
  removed.
