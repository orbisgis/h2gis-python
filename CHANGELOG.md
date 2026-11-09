# Changelog


- The native libraries are no longer committed in `native/`: they are
  downloaded from the GitHub release of H2GIS named in `native/H2GIS_RELEASE`
  (`python tools/update_native.py --download`), and checked against its
  `SHA256SUMS`. The wheels still ship the library of their platform.

- Conda packages (`recipe/`, rattler-build): one `noarch: python` package
  per platform (Linux, macOS, Windows), for Python 3.9 and later, published
  on anaconda.org.
- GitHub Actions CI (`.github/workflows/ci.yml`): tests on Linux, Windows and
  macOS, wheels tested after installation, sdist, conda packages;
  publication on PyPI (trusted publishing), TestPyPI, anaconda.org and a
  GitHub release, on a tag or a manual run.

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


