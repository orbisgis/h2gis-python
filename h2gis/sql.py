"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Safe composition of dynamic SQL, same API as ``psycopg.sql``::

    from h2gis import sql
    q = sql.SQL("SELECT {cols} FROM {table} WHERE ID = {id}").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, ["ID", "THE_GEOM"])),
        table=sql.Identifier("PUBLIC", "LIEUX"),
        id=sql.Placeholder())
    conn.execute(q, [42])

Watch out: H2 converts *unquoted* identifiers to upper case, and
``Identifier`` always quotes. ``Identifier("lieux")`` is the table "lieux",
not the table created by ``CREATE TABLE lieux`` (which is ``LIEUX``).
"""

from __future__ import annotations

import string
from typing import Any, Iterable, List, Optional, Sequence

from . import errors

__all__ = ["Composable", "Composed", "SQL", "Identifier", "Literal", "Placeholder",
           "NULL", "DEFAULT", "quote"]


def _adapters(context):
    if context is not None and hasattr(context, "adapters"):
        return context.adapters
    from .adapt import adapters
    return adapters


class Composable:
    """Base class of the objects that can be composed into a query."""

    def __init__(self, obj: Any):
        self._obj = obj

    def as_string(self, context: Any = None) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._obj!r})"

    def __add__(self, other: "Composable") -> "Composed":
        if isinstance(other, Composed):
            return Composed([self, *other._obj])
        if isinstance(other, Composable):
            return Composed([self, other])
        return NotImplemented

    def __mul__(self, n: int) -> "Composed":
        return Composed([self] * n)

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self._obj == other._obj  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self), repr(self._obj)))


class Composed(Composable):
    """A sequence of composables."""

    def __init__(self, seq: Iterable[Composable]):
        seq = [obj if isinstance(obj, Composable) else Literal(obj) for obj in seq]
        super().__init__(seq)

    def as_string(self, context: Any = None) -> str:
        return "".join(obj.as_string(context) for obj in self._obj)

    def __iter__(self):
        return iter(self._obj)

    def __add__(self, other: Composable) -> "Composed":
        if isinstance(other, Composed):
            return Composed([*self._obj, *other._obj])
        if isinstance(other, Composable):
            return Composed([*self._obj, other])
        return NotImplemented

    def join(self, joiner) -> "Composed":
        if isinstance(joiner, str):
            joiner = SQL(joiner)
        return joiner.join(self._obj)


class SQL(Composable):
    """A snippet of SQL, included verbatim. Use :meth:`format` to fill ``{}``."""

    _formatter = string.Formatter()

    def __init__(self, obj: str):
        if not isinstance(obj, str):
            raise TypeError(f"SQL values must be strings, got {type(obj).__name__}")
        super().__init__(obj)

    def as_string(self, context: Any = None) -> str:
        return self._obj

    def format(self, *args: Any, **kwargs: Any) -> Composed:
        rv: List[Composable] = []
        autonum: Optional[int] = 0
        for pre, name, spec, conv in self._formatter.parse(self._obj):
            if spec:
                raise ValueError("no format specification allowed in SQL.format()")
            if conv:
                raise ValueError("no format conversion allowed in SQL.format()")
            if pre:
                rv.append(SQL(pre))
            if name is None:
                continue
            if name.isdigit():
                if autonum:
                    raise ValueError("cannot switch from automatic field numbering to manual")
                rv.append(_as_composable(args[int(name)]))
                autonum = None
            elif not name:
                if autonum is None:
                    raise ValueError("cannot switch from manual field numbering to automatic")
                rv.append(_as_composable(args[autonum]))
                autonum += 1
            else:
                rv.append(_as_composable(kwargs[name]))
        return Composed(rv)

    def join(self, seq: Iterable[Any]) -> Composed:
        rv: List[Composable] = []
        for i, obj in enumerate(seq):
            if i:
                rv.append(self)
            rv.append(_as_composable(obj))
        return Composed(rv)


def _as_composable(obj) -> Composable:
    if isinstance(obj, Composable):
        return obj
    raise TypeError(
        f"SQL.format() arguments must be Composable (SQL, Identifier, Literal...), "
        f"got {type(obj).__name__}; wrap values in sql.Literal()")


class Identifier(Composable):
    """A quoted identifier: ``Identifier("PUBLIC", "LIEUX")`` -> ``"PUBLIC"."LIEUX"``."""

    def __init__(self, *strings: str):
        if not strings:
            raise TypeError("Identifier cannot be empty")
        for s in strings:
            if not isinstance(s, str):
                raise TypeError(f"SQL identifier parts must be strings, got {type(s).__name__}")
            if "\x00" in s:
                raise errors.DataError("NUL characters are not allowed in identifiers")
        super().__init__(strings)

    def as_string(self, context: Any = None) -> str:
        return ".".join('"' + s.replace('"', '""') + '"' for s in self._obj)

    def __repr__(self) -> str:
        return f"Identifier({', '.join(map(repr, self._obj))})"


class Literal(Composable):
    """A Python value rendered as an SQL literal."""

    def as_string(self, context: Any = None) -> str:
        return _adapters(context).literal(self._obj)


class Placeholder(Composable):
    """``%s`` or ``%(name)s``, to be filled by the execute() parameters."""

    def __init__(self, name: str = "", format: str = "s"):  # noqa: A002 - psycopg name
        if not isinstance(name, str):
            raise TypeError("placeholder name must be a string")
        if ")" in name:
            raise ValueError(f"invalid placeholder name: {name!r}")
        if format not in ("s", "b", "t"):
            raise ValueError(f"invalid placeholder format: {format!r}")
        super().__init__(name)
        self._format = format

    def as_string(self, context: Any = None) -> str:
        return f"%({self._obj}){self._format}" if self._obj else f"%{self._format}"


def quote(obj: Any, context: Any = None) -> str:
    """Return ``obj`` as an SQL literal string."""
    return _adapters(context).literal(obj)


NULL = SQL("NULL")
DEFAULT = SQL("DEFAULT")


def as_query_string(query: Any, context: Any = None) -> str:
    """Accept ``str``, ``bytes`` or :class:`Composable` as a query."""
    if isinstance(query, str):
        return query
    if isinstance(query, Composable):
        return query.as_string(context)
    if isinstance(query, (bytes, bytearray)):
        return bytes(query).decode("utf-8")
    raise TypeError(f"query must be a string or a sql.Composable, got {type(query).__name__}")
