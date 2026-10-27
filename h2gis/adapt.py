"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Conversion between Python objects and H2 values, in the spirit of
``psycopg.adapt`` but with plain functions instead of Dumper/Loader classes.

Python -> H2 ("dump")
    Each parameter becomes either a native bind ``(kind, value)`` used with
    prepared statements, or an SQL literal used for client side binding and
    by :class:`h2gis.sql.Literal`. Geometries, dates, UUIDs... are wrapped in a
    ``CAST(? AS ...)`` so that H2 knows the parameter type.

H2 -> Python ("load")
    Values decoded from the native buffer are converted according to the
    column type: Shapely geometries (with their SRID), ``datetime`` objects...

Custom adaptation::

    h2gis.adapters.register_dumper(MyPoint, lambda p: shapely.Point(p.x, p.y))
    h2gis.adapters.register_loader("UUID", uuid.UUID)
"""

from __future__ import annotations

import datetime as _dt
import decimal
import json
import math
import re
import uuid
from typing import Any, Callable, Dict, Optional, Tuple, Type

from . import errors

__all__ = ["AdaptersMap", "adapters", "Geometry", "Json", "ColumnType"]


class ColumnType:
    """Type codes of the native result buffer (``org.h2gis.graalvm.TypeCodes``)."""
    INT = 1
    LONG = 2
    FLOAT = 3
    DOUBLE = 4
    BOOLEAN = 5
    STRING = 6
    TEMPORAL = 7  # DATE, TIME [WITH TIME ZONE], TIMESTAMP [WITH TIME ZONE], ISO strings
    DATE = TEMPORAL
    GEOMETRY = 8  # EWKB
    BINARY = 9
    DECIMAL = 10  # exact decimal string
    JSON = 11
    UUID = 12
    OTHER = 99    # anything else, as ResultSet.getString()

    NAMES = {1: "INTEGER", 2: "BIGINT", 3: "REAL", 4: "DOUBLE PRECISION",
             5: "BOOLEAN", 6: "CHARACTER VARYING", 7: "TIMESTAMP",
             8: "GEOMETRY", 9: "BINARY VARYING", 10: "NUMERIC", 11: "JSON",
             12: "UUID", 99: "OTHER"}


class Geometry:
    """Wrap a Shapely geometry to force its SRID when passed as a parameter::

        conn.execute("INSERT INTO t VALUES (%s)", [Geometry(point, srid=4326)])
    """

    __slots__ = ("geom", "srid")

    def __init__(self, geom, srid: Optional[int] = None):
        self.geom = geom
        self.srid = srid

    def ewkb(self) -> bytes:
        import shapely
        geom = self.geom
        if self.srid is not None:
            geom = shapely.set_srid(geom, int(self.srid))
        return shapely.to_wkb(geom, include_srid=True)


class Json:
    """Wrap a Python object to pass it as a JSON value (like ``psycopg.types.json.Json``)::

        conn.execute("INSERT INTO t(doc) VALUES (%s)", [Json({"a": 1})])
    """

    __slots__ = ("obj", "dumps")

    def __init__(self, obj, dumps: Callable[[Any], str] = json.dumps):
        self.obj = obj
        self.dumps = dumps

    def text(self) -> str:
        return self.dumps(self.obj)


def _is_geometry(obj) -> bool:
    try:
        from shapely.geometry.base import BaseGeometry
    except ImportError:  # pragma: no cover
        return False
    return isinstance(obj, BaseGeometry)


_LONG_MIN, _LONG_MAX = -(2 ** 63), 2 ** 63 - 1

#: Pseudo cast returned by bind_value(): the placeholder becomes "? FORMAT JSON".
FORMAT_JSON = "FORMAT JSON"


def _quote_string(text: str) -> str:
    if "\x00" in text:
        raise errors.DataError("NUL characters are not allowed in H2 strings")
    return "'" + text.replace("'", "''") + "'"


def _datetime_sql_type(value) -> str:
    if isinstance(value, _dt.datetime):
        return "TIMESTAMP WITH TIME ZONE" if value.tzinfo is not None else "TIMESTAMP"
    if isinstance(value, _dt.time):
        return "TIME WITH TIME ZONE" if value.tzinfo is not None else "TIME"
    return "DATE"


def _iso(value) -> str:
    if isinstance(value, _dt.datetime):
        return value.isoformat(sep=" ")
    return value.isoformat()


class AdaptersMap:
    """Registry of dumpers (Python -> H2) and loaders (H2 -> Python).

    The global :data:`adapters` is used by default; each connection gets its
    own copy (``conn.adapters``) so that customizations can stay local.
    """

    def __init__(self, template: Optional["AdaptersMap"] = None):
        self._dumpers: Dict[Type, Callable[[Any], Any]] = dict(template._dumpers) if template else {}
        self._loaders: Dict[Any, Callable[[Any], Any]] = dict(template._loaders) if template else {}

    # -- registration ---------------------------------------------------------

    def register_dumper(self, cls: Type, func: Callable[[Any], Any]) -> None:
        """``func(obj)`` must return an object that h2gis already knows how to dump."""
        self._dumpers[cls] = func

    def register_loader(self, type_name, func: Callable[[Any], Any]) -> None:
        """Convert values of an H2 type (``"UUID"``, ``"GEOMETRY"``...) or type code.

        ``func`` receives the value decoded by the default rules (a string for
        most non numeric types) and is not called for NULLs.
        """
        key = type_name.upper() if isinstance(type_name, str) else int(type_name)
        self._loaders[key] = func

    def _custom_dump(self, obj):
        for cls in type(obj).__mro__:
            func = self._dumpers.get(cls)
            if func is not None:
                return True, func(obj)
        return False, None

    # -- Python -> H2 ---------------------------------------------------------

    def bind_value(self, obj) -> Tuple[str, Any, Optional[str]]:
        """Return ``(kind, value, cast)`` for a native bind.

        ``kind`` is one of ``null``, ``long``, ``double``, ``string``, ``blob``
        or ``literal`` (the value can't be bound: inline the SQL literal in
        ``value``). ``cast`` is an SQL type to wrap the placeholder in.
        """
        found, new = self._custom_dump(obj)
        if found:
            return self.bind_value(new)
        if obj is None:
            return "null", None, None
        if isinstance(obj, bool):
            return "long", int(obj), "BOOLEAN"
        if isinstance(obj, int):
            if _LONG_MIN <= obj <= _LONG_MAX:
                return "long", obj, None
            return "string", str(obj), "NUMERIC"
        if isinstance(obj, float):
            return "double", obj, None
        if isinstance(obj, decimal.Decimal):
            # DECFLOAT keeps every digit; CAST(? AS NUMERIC) would round to scale 0
            return "string", str(obj), "DECFLOAT"
        if isinstance(obj, str):
            if "\x00" in obj:
                raise errors.DataError("NUL characters are not allowed in H2 strings")
            return "string", obj, None
        if isinstance(obj, (bytes, bytearray, memoryview)):
            return "blob", bytes(obj), None
        if isinstance(obj, (_dt.date, _dt.time)):  # datetime is a date subclass
            return "string", _iso(obj), _datetime_sql_type(obj)
        if isinstance(obj, uuid.UUID):
            return "string", str(obj), "UUID"
        if isinstance(obj, Json):
            return "string", obj.text(), FORMAT_JSON
        if isinstance(obj, Geometry):
            return "blob", obj.ewkb(), "GEOMETRY"
        if _is_geometry(obj):
            return "blob", Geometry(obj).ewkb(), "GEOMETRY"
        if _is_numpy_scalar(obj):
            return self.bind_value(obj.item())
        # lists, tuples...: no native bind, inline a literal
        return "literal", self.literal(obj), None

    def literal(self, obj) -> str:
        """Return a safe SQL literal for ``obj`` (used for client side binding)."""
        found, new = self._custom_dump(obj)
        if found:
            return self.literal(new)
        if obj is None:
            return "NULL"
        if isinstance(obj, bool):
            return "TRUE" if obj else "FALSE"
        if isinstance(obj, int):
            text = str(obj)
            return text if _LONG_MIN <= obj <= _LONG_MAX else f"CAST({text} AS NUMERIC)"
        if isinstance(obj, float):
            if math.isnan(obj):
                return "CAST('NaN' AS DOUBLE PRECISION)"
            if math.isinf(obj):
                return "CAST('{}Infinity' AS DOUBLE PRECISION)".format("-" if obj < 0 else "")
            return f"CAST({obj!r} AS DOUBLE PRECISION)"
        if isinstance(obj, decimal.Decimal):
            return f"CAST('{obj}' AS DECFLOAT)"
        if isinstance(obj, str):
            return _quote_string(obj)
        if isinstance(obj, (bytes, bytearray, memoryview)):
            return "X'" + bytes(obj).hex() + "'"
        if isinstance(obj, (_dt.date, _dt.time)):
            return f"{_datetime_sql_type(obj)} '{_iso(obj)}'"
        if isinstance(obj, uuid.UUID):
            return f"CAST('{obj}' AS UUID)"
        if isinstance(obj, Json):
            return f"{_quote_string(obj.text())} FORMAT JSON"
        if isinstance(obj, Geometry):
            return f"CAST(X'{obj.ewkb().hex()}' AS GEOMETRY)"
        if _is_geometry(obj):
            return f"CAST(X'{Geometry(obj).ewkb().hex()}' AS GEOMETRY)"
        if _is_numpy_scalar(obj):
            return self.literal(obj.item())
        if isinstance(obj, (list, tuple)):
            return "ARRAY[" + ", ".join(self.literal(x) for x in obj) + "]"
        raise errors.ProgrammingError(
            f"cannot adapt type {type(obj).__name__!r}; register a dumper with "
            "h2gis.adapters.register_dumper()")

    # -- H2 -> Python ---------------------------------------------------------

    def loader(self, type_code: int, type_name: Optional[str]) -> Callable[[Any], Any]:
        """Return the function converting non NULL values of a column."""
        base = _DEFAULT_LOADERS.get(type_code, _identity)
        name = (type_name or "").upper()
        custom = self._loaders.get(name) if name else None
        if custom is None:
            custom = self._loaders.get(type_code)
        if custom is None:
            return base
        if base is _identity:
            return custom
        return lambda v: custom(base(v))


def _is_numpy_scalar(obj) -> bool:
    mod = type(obj).__module__
    return mod == "numpy" and hasattr(obj, "item")


def _identity(value):
    return value


def _load_geometry(value: bytes):
    import shapely
    return shapely.from_wkb(value)


def load_geometry_column(values: list) -> list:
    """Vectorized :func:`_load_geometry` for a whole column (None stays None)."""
    import numpy as np
    import shapely
    arr = np.array(values, dtype=object)
    return shapely.from_wkb(arr).tolist()


_DATE_RE = re.compile(r"^(-?\d{4,})-(\d\d)-(\d\d)$")
_TIME_RE = re.compile(r"^(\d\d):(\d\d)(?::(\d\d)(?:\.(\d+))?)?(Z|[+-]\d\d(?::?\d\d(?::?\d\d)?)?)?$")
_TS_RE = re.compile(
    r"^(-?\d{4,})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d)(?:\.(\d+))?)?"
    r"(Z|[+-]\d\d(?::?\d\d(?::?\d\d)?)?)?$")


def _micro(frac: Optional[str]) -> int:
    return int((frac or "0")[:6].ljust(6, "0"))


def _tz(text: Optional[str]):
    if not text:
        return None
    if text == "Z":
        return _dt.timezone.utc
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    hours, minutes, seconds = int(digits[0:2]), int(digits[2:4] or 0), int(digits[4:6] or 0)
    return _dt.timezone(sign * _dt.timedelta(hours=hours, minutes=minutes, seconds=seconds))


def _load_temporal(value: str):
    """Parse the ISO strings of DATE, TIME and TIMESTAMP [WITH TIME ZONE] columns.

    Values out of Python's range (year 0 or before, year > 9999) stay strings.
    """
    try:
        m = _TS_RE.match(value)
        if m:
            y, mo, d, h, mi, s, frac, tz = m.groups()
            return _dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0),
                                _micro(frac), tzinfo=_tz(tz))
        m = _DATE_RE.match(value)
        if m:
            return _dt.date(*map(int, m.groups()))
        m = _TIME_RE.match(value)
        if m:
            h, mi, s, frac, tz = m.groups()
            return _dt.time(int(h), int(mi), int(s or 0), _micro(frac), tzinfo=_tz(tz))
    except ValueError:
        pass
    return value


_DEFAULT_LOADERS: Dict[int, Callable[[Any], Any]] = {
    ColumnType.TEMPORAL: _load_temporal,
    ColumnType.GEOMETRY: _load_geometry,
    ColumnType.DECIMAL: decimal.Decimal,
    ColumnType.JSON: json.loads,
    ColumnType.UUID: uuid.UUID,
}

#: The global adapters map, template of every new connection.
adapters = AdaptersMap()
