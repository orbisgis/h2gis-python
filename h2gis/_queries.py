"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Query preparation, following psycopg 3 rules:

* placeholders are ``%s`` (positional) or ``%(name)s`` (named); ``%b`` and
  ``%t`` are accepted as synonyms of ``%s``;
* when parameters are passed, a literal ``%`` must be written ``%%``
  (everywhere, string literals included, exactly like psycopg);
* without parameters the query is sent verbatim, ``%`` included.

The query is converted to JDBC ``?`` placeholders for native binding, or the
values are inlined as SQL literals when the library can't bind parameters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, List, Optional, Tuple, Union

from . import errors
from .adapt import FORMAT_JSON, AdaptersMap

_PLACEHOLDER_RE = re.compile(r"%(?:\((?P<name>[^)]*)\))?(?P<fmt>.?)", re.S)


class _Ph:
    __slots__ = ("key",)

    def __init__(self, key: Union[int, str]):
        self.key = key


def split_query(query: str) -> List[Union[str, _Ph]]:
    """Split a query into SQL text parts and placeholders."""
    parts: List[Union[str, _Ph]] = []
    pos = 0
    index = 0
    kinds = set()
    for m in _PLACEHOLDER_RE.finditer(query):
        name, fmt = m.group("name"), m.group("fmt")
        if fmt == "%" and name is None:
            parts.append(query[pos:m.start()] + "%")
            pos = m.end()
            continue
        if fmt not in ("s", "b", "t"):
            got = m.group(0)
            if not fmt:
                raise errors.ProgrammingError(f"incomplete placeholder: {got!r}")
            raise errors.ProgrammingError(
                f"only '%s', '%b', '%t' are allowed as placeholders, got {got!r}")
        parts.append(query[pos:m.start()])
        if name is None:
            parts.append(_Ph(index))
            index += 1
            kinds.add("pos")
        else:
            if not name:
                raise errors.ProgrammingError("empty placeholder name: '%()s'")
            parts.append(_Ph(name))
            kinds.add("name")
        pos = m.end()
    parts.append(query[pos:])
    if len(kinds) > 1:
        raise errors.ProgrammingError("positional and named placeholders can't be mixed")
    return parts


def _value_for(key, params, positional: bool):
    if positional:
        return params[key]
    try:
        return params[key]
    except KeyError:
        raise errors.ProgrammingError(f"query parameter missing: {key!r}") from None


def _check_params(parts, params) -> bool:
    """Validate params against the placeholders; return True if positional."""
    keys = [p.key for p in parts if isinstance(p, _Ph)]
    positional = not keys or isinstance(keys[0], int)
    if isinstance(params, Mapping):
        if keys and positional:
            raise errors.ProgrammingError("query has positional placeholders but a mapping was passed")
        return False
    if isinstance(params, (str, bytes)) or not isinstance(params, Sequence):
        raise errors.ProgrammingError(
            f"query parameters should be a sequence or a mapping, got {type(params).__name__}")
    if keys and not positional:
        raise errors.ProgrammingError("query has named placeholders but a sequence was passed")
    if len(keys) != len(params):
        raise errors.ProgrammingError(
            f"the query has {len(keys)} placeholders but {len(params)} parameters were passed")
    return True


def render_literals(query: str, params, adapters: AdaptersMap) -> str:
    """Inline every parameter as an SQL literal (client side binding)."""
    if params is None:
        return query
    parts = split_query(query)
    positional = _check_params(parts, params)
    out = []
    for p in parts:
        out.append(adapters.literal(_value_for(p.key, params, positional))
                   if isinstance(p, _Ph) else p)
    return "".join(out)


def render_binds(query: str, params, adapters: AdaptersMap) -> Tuple[str, List[Tuple[str, Any]]]:
    """Return the query with ``?`` placeholders and the ordered list of binds."""
    if params is None:
        return query, []
    parts = split_query(query)
    positional = _check_params(parts, params)
    out: List[str] = []
    binds: List[Tuple[str, Any]] = []
    for p in parts:
        if not isinstance(p, _Ph):
            out.append(p)
            continue
        kind, value, cast = adapters.bind_value(_value_for(p.key, params, positional))
        if kind == "literal":
            out.append(value)
            continue
        if cast == FORMAT_JSON:
            out.append("? FORMAT JSON")
        else:
            out.append(f"CAST(? AS {cast})" if cast else "?")
        binds.append((kind, value))
    return "".join(out), binds


# --- statement classification ---------------------------------------------

_LEADING_RE = re.compile(r"(?:\s+|--[^\n]*(?:\n|$)|/\*.*?\*/|\()*", re.S)
_QUERY_KEYWORDS = {"SELECT", "WITH", "VALUES", "TABLE", "SHOW", "EXPLAIN", "CALL",
                   "SCRIPT", "HELP"}
_DELTA_RE = re.compile(r"\b(?:FINAL|NEW|OLD)\s+TABLE\s*\(", re.I)


def first_keyword(query: str) -> str:
    m = _LEADING_RE.match(query)
    rest = query[m.end():] if m else query
    word = re.match(r"[A-Za-z_]+", rest)
    return word.group(0).upper() if word else ""


def is_query(query: str) -> Optional[bool]:
    """Guess if a statement returns rows. None if unknown."""
    kw = first_keyword(query)
    if not kw:
        return None
    return kw in _QUERY_KEYWORDS


def has_side_effects(query: str) -> bool:
    """True if a query can modify data (data change delta table, CALL)."""
    return bool(_DELTA_RE.search(query)) or first_keyword(query) == "CALL"
