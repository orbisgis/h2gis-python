"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

pandas / GeoPandas integration (pandas and geopandas are optional
dependencies, imported on first use)::

    gdf = h2gis.read_gdf(conn, "SELECT * FROM LIEUX")
    h2gis.to_h2gis(gdf, "LIEUX_COPIE", conn, if_exists="replace")

The native result is column oriented, so frames are built column by column
without going through rows.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import re
from typing import Any, Iterator, List, Optional, Sequence, Union

from . import errors, sql
from .adapt import ColumnType

__all__ = ["read_df", "read_gdf", "to_h2gis"]

_INT_CODES = (ColumnType.INT, ColumnType.LONG)


def _pd():
    try:
        import pandas
    except ImportError as exc:  # pragma: no cover
        raise ImportError("pandas is required: pip install pandas") from exc
    return pandas


def _gpd():
    try:
        import geopandas
    except ImportError as exc:  # pragma: no cover
        raise ImportError("geopandas is required: pip install geopandas") from exc
    return geopandas


def _cursor_for(conn, query, params, chunksize):
    cur = conn.cursor()
    if chunksize:
        cur._check()
        with conn._lock:
            cur._reset()
            cur._run(query, params, None, batch=chunksize)
    else:
        cur.execute(query, params)
    if cur.description is None:
        cur.close()
        raise errors.ProgrammingError("the query doesn't return rows")
    return cur


def _series(pd, values: list, type_code: int, coerce_float: bool = True):
    if coerce_float and type_code == ColumnType.DECIMAL:
        import numpy as np
        return np.array([np.nan if v is None else float(v) for v in values], dtype="float64")
    if type_code in _INT_CODES and any(v is None for v in values):
        return pd.array(values, dtype="Int64")
    if type_code == ColumnType.BOOLEAN and any(v is None for v in values):
        return pd.array(values, dtype="boolean")
    return values


def _frame(pd, cur, columns: List[list], coerce_float: bool = True):
    desc = cur.description
    data = {i: _series(pd, col, d.type_code, coerce_float)
            for i, (col, d) in enumerate(zip(columns, desc))}
    df = pd.DataFrame(data, columns=range(len(desc)))
    if not columns or not columns[0]:  # empty result: keep integer dtypes
        for i, d in enumerate(desc):
            if d.type_code in _INT_CODES:
                df[i] = df[i].astype("Int64")
    df.columns = [d.name for d in desc]
    return df


def _chunks(cur, chunksize: Optional[int]) -> Iterator[List[list]]:
    if not chunksize:
        yield cur.fetch_column_lists()
        return
    first = True
    while True:
        cols = cur.fetch_column_lists(chunksize)
        if not cols or not cols[0]:
            if first:
                yield cols
            return
        first = False
        yield cols


def read_df(conn, query, params=None, *, chunksize: Optional[int] = None,
            coerce_float: bool = True):
    """Run a query and return a pandas DataFrame (geometries stay Shapely objects).

    With ``chunksize``, return an iterator of DataFrames of at most
    ``chunksize`` rows, read in batches from the native library.
    NUMERIC/DECIMAL columns become float64 unless ``coerce_float=False``
    (then ``decimal.Decimal`` objects), as with ``pandas.read_sql``.
    """
    pd = _pd()
    cur = _cursor_for(conn, query, params, chunksize)

    def gen():
        try:
            for cols in _chunks(cur, chunksize):
                yield _frame(pd, cur, cols, coerce_float)
        finally:
            cur.close()

    if chunksize:
        return gen()
    return next(gen())


def _srid_crs(gpd, series):
    import shapely
    import numpy as np
    values = np.asarray(series, dtype=object)
    mask = np.array([v is not None for v in values], dtype=bool)
    if not mask.any():
        return None
    srids = set(int(s) for s in shapely.get_srid(values[mask]))
    srids.discard(0)
    if not srids:
        return None
    if len(srids) > 1:
        raise errors.DataError(
            f"geometry column {series.name!r} mixes SRIDs {sorted(srids)}; pass crs= "
            "or transform the geometries in SQL (ST_Transform)")
    return f"EPSG:{srids.pop()}"


def read_gdf(conn, query, params=None, *, geometry: Optional[str] = None,
             crs: Any = None, chunksize: Optional[int] = None, coerce_float: bool = True):
    """Run a query and return a GeoDataFrame.

    Parameters
    ----------
    geometry:
        Name of the active geometry column. Default: the first GEOMETRY column.
    crs:
        CRS of the result. Default: taken from the SRID of the geometries
        (``EPSG:<srid>``), None if the SRID is 0.
    chunksize:
        Return an iterator of GeoDataFrames of at most ``chunksize`` rows.
    coerce_float:
        NUMERIC/DECIMAL columns as float64 (default) or ``decimal.Decimal``.

    Other geometry columns are converted to GeoSeries as well. Raises
    ProgrammingError if the result has no geometry column.
    """
    pd = _pd()
    gpd = _gpd()
    cur = _cursor_for(conn, query, params, chunksize)
    desc = cur.description
    geom_cols = [d.name for d in desc if d.type_code == ColumnType.GEOMETRY]
    if geometry is None:
        if not geom_cols:
            cur.close()
            raise errors.ProgrammingError(
                "the query returns no GEOMETRY column; use read_df() or pass geometry=")
        geometry = geom_cols[0]
    elif geometry not in [d.name for d in desc]:
        cur.close()
        raise errors.ProgrammingError(
            f"no column {geometry!r} in the result; columns are {[d.name for d in desc]} "
            "(H2 upper-cases unquoted names)")
    elif geometry not in geom_cols:
        geom_cols.append(geometry)

    known_crs: dict = {}  # keep the CRS across chunks (a chunk may only hold NULLs)

    def build(cols):
        df = _frame(pd, cur, cols, coerce_float)
        if df.columns.duplicated().any():
            raise errors.ProgrammingError(
                f"duplicate column names {sorted(set(df.columns[df.columns.duplicated()]))}: use aliases")
        series = {}
        for name in geom_cols:
            values = df[name]
            if name == geometry and crs is not None:
                col_crs = crs
            else:
                col_crs = _srid_crs(gpd, values) or known_crs.get(name)
                if col_crs is not None:
                    known_crs.setdefault(name, col_crs)
            series[name] = gpd.GeoSeries(list(values), index=df.index, crs=col_crs, name=name)
        for name, s in series.items():
            df[name] = s
        return gpd.GeoDataFrame(df, geometry=geometry, crs=series[geometry].crs)

    def gen():
        try:
            for cols in _chunks(cur, chunksize):
                yield build(cols)
        finally:
            cur.close()

    if chunksize:
        return gen()
    return next(gen())


# --- writing ----------------------------------------------------------------

_SIMPLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GEOM_TYPES = {"Point": "POINT", "LineString": "LINESTRING", "Polygon": "POLYGON",
               "MultiPoint": "MULTIPOINT", "MultiLineString": "MULTILINESTRING",
               "MultiPolygon": "MULTIPOLYGON", "GeometryCollection": "GEOMETRYCOLLECTION",
               "LinearRing": "LINESTRING"}


def _ident(name: Union[str, sql.Identifier]) -> sql.Composable:
    """Identifier with the semantics of an unquoted name in H2 (upper-cased)."""
    if isinstance(name, sql.Composable):
        return name
    name = str(name)
    parts = name.split(".") if all(_SIMPLE_NAME_RE.match(p) for p in name.split(".")) else [name]
    return sql.Identifier(*[p.upper() if _SIMPLE_NAME_RE.match(p) else p for p in parts])


def _geom_sql_type(series, srid: int) -> str:
    import shapely
    import numpy as np
    values = np.asarray(series.values, dtype=object)
    present = values[[v is not None for v in values]]
    gtype = "GEOMETRY"
    if len(present):
        types = set(shapely.get_type_id(present).tolist())
        has_z = shapely.has_z(present)
        names = {g.geom_type for g in present[:1]} if len(types) == 1 else set()
        if len(types) == 1 and (has_z.all() or not has_z.any()):
            base = _GEOM_TYPES.get(next(iter(names)), "GEOMETRY")
            gtype = base + (" Z" if has_z.all() and base != "GEOMETRY" else "")
    return f"GEOMETRY({gtype}, {srid})" if srid else (f"GEOMETRY({gtype})" if gtype != "GEOMETRY" else "GEOMETRY")


def _sql_type(series) -> str:
    pd = _pd()
    from pandas.api import types as pt
    dtype = series.dtype
    if isinstance(dtype, pd.DatetimeTZDtype):
        return "TIMESTAMP WITH TIME ZONE"
    if pt.is_bool_dtype(dtype):
        return "BOOLEAN"
    if pt.is_integer_dtype(dtype):
        return "BIGINT" if dtype.itemsize >= 8 else "INTEGER"
    if pt.is_float_dtype(dtype):
        return "REAL" if dtype.itemsize == 4 else "DOUBLE PRECISION"
    if pt.is_datetime64_dtype(dtype):
        return "TIMESTAMP"
    if pt.is_timedelta64_dtype(dtype):
        raise errors.NotSupportedError(f"column {series.name!r}: timedelta is not supported")
    sample = next((v for v in series if v is not None and not _isna(v)), None)
    if sample is None or isinstance(sample, str):
        return "CHARACTER VARYING"
    if isinstance(sample, bool):
        return "BOOLEAN"
    if isinstance(sample, int):
        return "BIGINT"
    if isinstance(sample, float):
        return "DOUBLE PRECISION"
    if isinstance(sample, decimal.Decimal):
        return "NUMERIC"
    if isinstance(sample, _dt.datetime):
        return "TIMESTAMP WITH TIME ZONE" if sample.tzinfo else "TIMESTAMP"
    if isinstance(sample, _dt.date):
        return "DATE"
    if isinstance(sample, _dt.time):
        return "TIME"
    if isinstance(sample, (bytes, bytearray)):
        return "BINARY VARYING"
    raise errors.NotSupportedError(
        f"column {series.name!r}: can't map Python type {type(sample).__name__} to H2")


def _isna(value) -> bool:
    try:
        result = _pd().isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, (bool,)) or getattr(result, "ndim", 1) == 0 else False


def _py(value):
    """Convert pandas/numpy scalars to plain Python values (NaN/NaT/NA -> None)."""
    if value is None:
        return None
    if _isna(value):
        return None
    pd = _pd()
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if type(value).__module__ == "numpy":
        if hasattr(value, "astype") and str(getattr(value, "dtype", "")).startswith("datetime64"):
            return pd.Timestamp(value).to_pydatetime()
        return value.item()
    return value


def to_h2gis(df, name: Union[str, sql.Identifier], conn, *, if_exists: str = "fail",
             index: bool = False, srid: Optional[int] = None, chunksize: int = 500,
             spatial_index: bool = False) -> int:
    """Write a (Geo)DataFrame to a table; return the number of rows inserted.

    Parameters
    ----------
    name:
        Table name. A plain name (letters, digits, ``_``, optionally
        ``SCHEMA.TABLE``) is upper-cased like an unquoted name in H2, so
        ``to_h2gis(gdf, "lieux", conn)`` writes ``LIEUX``. Column names follow
        the same rule. Pass :class:`h2gis.sql.Identifier` to keep the exact case.
    if_exists:
        ``"fail"`` (error if the table exists), ``"replace"`` (drop it first)
        or ``"append"``.
    index:
        Also write the index as column(s).
    srid:
        SRID of the geometry columns. Default: ``df.crs.to_epsg()`` for a
        GeoDataFrame, else the SRID of the geometries.
    chunksize:
        Rows per INSERT statement.
    spatial_index:
        Create a spatial index on each geometry column.
    """
    pd = _pd()
    if if_exists not in ("fail", "replace", "append"):
        raise ValueError("if_exists must be 'fail', 'replace' or 'append'")
    if index:
        df = df.reset_index()
    if df.columns.duplicated().any():
        raise errors.ProgrammingError("duplicate column names in the DataFrame")

    from shapely.geometry.base import BaseGeometry
    import shapely

    geom_cols = []
    for col in df.columns:
        series = df[col]
        if getattr(series.dtype, "name", "") == "geometry" or (
                series.dtype == object
                and isinstance(next((v for v in series if v is not None), None), BaseGeometry)):
            geom_cols.append(col)

    def col_srid(col) -> int:
        if srid is not None:
            return int(srid)
        crs = getattr(df[col], "crs", None)
        if crs is not None:
            epsg = crs.to_epsg()
            if epsg is None:
                raise errors.DataError(
                    f"the CRS of column {col!r} has no EPSG code; pass srid=")
            return int(epsg)
        values = [v for v in df[col] if v is not None]
        found = {int(s) for s in shapely.get_srid(values)} if values else set()
        found.discard(0)
        return found.pop() if len(found) == 1 else 0

    table = _ident(name)
    col_defs, col_idents, converters = [], [], []
    for col in df.columns:
        ident = _ident(str(col))
        col_idents.append(ident)
        if col in geom_cols:
            s = col_srid(col)
            col_defs.append(sql.SQL("{} {}").format(ident, sql.SQL(_geom_sql_type(df[col], s))))
            converters.append(_geom_converter(s))
        else:
            col_defs.append(sql.SQL("{} {}").format(ident, sql.SQL(_sql_type(df[col]))))
            converters.append(_py)

    with conn.transaction():
        if if_exists == "replace":
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
        create = "CREATE TABLE IF NOT EXISTS {} ({})" if if_exists == "append" else "CREATE TABLE {} ({})"
        conn.execute(sql.SQL(create).format(table, sql.SQL(", ").join(col_defs)))

        ncols = len(col_idents)
        inserted = 0
        if ncols:
            row_ph = sql.SQL("(" + ", ".join(["%s"] * ncols) + ")")
            columns_sql = sql.SQL(", ").join(col_idents)
            arrays = [df[c].tolist() for c in df.columns]
            n = len(df)
            for start in range(0, n, max(1, chunksize)):
                stop = min(n, start + max(1, chunksize))
                params: List[Any] = []
                for i in range(start, stop):
                    params.extend(conv(arr[i]) for conv, arr in zip(converters, arrays))
                q = sql.SQL("INSERT INTO {} ({}) VALUES {}").format(
                    table, columns_sql, sql.SQL(", ").join([row_ph] * (stop - start)))
                cur = conn.execute(q, params)
                inserted += max(cur.rowcount, 0)
        if spatial_index:
            for col in geom_cols:
                conn.execute(sql.SQL("CREATE SPATIAL INDEX ON {} ({})").format(table, _ident(str(col))))
    return inserted


def _geom_converter(srid: int):
    import shapely
    from .adapt import Geometry

    def convert(value):
        if value is None or _isna(value):
            return None
        return Geometry(value, srid if srid else None)
    return convert
