"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Row factories, same contract as ``psycopg.rows``: a row factory is called
with the cursor once its ``description`` is known and returns a function
turning a sequence of values into a row::

    conn = h2gis.connect(path, row_factory=dict_row)
    cur = conn.cursor(row_factory=class_row(Place))
"""

from __future__ import annotations

import functools
import re
from collections import namedtuple
from typing import Any, Callable, Sequence

from . import errors

__all__ = ["tuple_row", "dict_row", "namedtuple_row", "class_row", "args_row", "kwargs_row"]


def _names(cursor):
    if cursor.description is None:
        raise errors.ProgrammingError("the last operation didn't produce a result")
    return [c.name for c in cursor.description]


def tuple_row(cursor) -> Callable[[Sequence[Any]], tuple]:
    """Rows as tuples (the default)."""
    return tuple


def dict_row(cursor) -> Callable[[Sequence[Any]], dict]:
    """Rows as ``{column name: value}``. Duplicate names: the last one wins."""
    names = _names(cursor)
    return lambda values: dict(zip(names, values))


@functools.lru_cache(512)
def _make_nt(names: tuple):
    fields = []
    for i, name in enumerate(names):
        field = re.sub(r"\W", "_", name)
        if not field or field[0].isdigit() or field[0] == "_":
            field = f"f{field}" if field else f"f{i}"
        fields.append(field)
    return namedtuple("Row", fields, rename=True)


def namedtuple_row(cursor) -> Callable[[Sequence[Any]], tuple]:
    """Rows as named tuples (invalid identifiers are sanitized)."""
    nt = _make_nt(tuple(_names(cursor)))
    return nt._make


def class_row(cls):
    """Rows as ``cls(**{name: value})``."""
    def factory(cursor):
        names = _names(cursor)
        return lambda values: cls(**dict(zip(names, values)))
    return factory


def args_row(func):
    """Rows as ``func(*values)``."""
    def factory(cursor):
        return lambda values: func(*values)
    return factory


def kwargs_row(func):
    """Rows as ``func(**{name: value})``."""
    def factory(cursor):
        names = _names(cursor)
        return lambda values: func(**dict(zip(names, values)))
    return factory
