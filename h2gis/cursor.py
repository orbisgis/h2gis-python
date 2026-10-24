"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

DB-API 2.0 cursor with the psycopg 3 extensions (``stream()``, row factories,
``execute()`` returning the cursor, iteration).
"""

from __future__ import annotations

from collections import namedtuple
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

from . import errors
from ._buffer import Chunk, decode
from ._queries import is_query, render_binds, render_literals
from .adapt import ColumnType, _identity, _load_geometry, load_geometry_column
from .sql import as_query_string

__all__ = ["Cursor", "Column"]

#: Rows sent per native batch by executemany().
EXECUTEMANY_BATCH = 10000

_ColumnBase = namedtuple(
    "_ColumnBase", "name type_code display_size internal_size precision scale null_ok")


class Column(_ColumnBase):
    """An item of :attr:`Cursor.description` (a 7-items sequence, PEP 249).

    ``type_name`` is the H2 type name (``"GEOMETRY(POINT, 4326)"``,
    ``"TIMESTAMP"``...); ``type_code`` the buffer type code
    (:class:`h2gis.adapt.ColumnType`).
    """

    def __new__(cls, name: str, type_code: int, type_name: Optional[str] = None):
        self = super().__new__(cls, name, type_code, None, None, None, None, None)
        self._type_name = type_name
        return self

    @property
    def type_name(self) -> str:
        return self._type_name or ColumnType.NAMES.get(self.type_code, "OTHER")


class Cursor:
    """Execute statements and fetch their results.

    Created by :meth:`Connection.cursor`. By default ``execute()`` reads the
    whole result in one native call, like psycopg's client cursor; use
    :meth:`stream` to read big results in batches.
    """

    arraysize: int = 1
    """Default number of rows returned by :meth:`fetchmany`."""

    def __init__(self, connection, row_factory: Optional[Callable] = None):
        self._conn = connection
        self._row_factory = row_factory or connection.row_factory
        self._closed = False
        self._lib = connection._lib
        self._reset()

    # -- properties -----------------------------------------------------------

    @property
    def connection(self):
        return self._conn

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def description(self) -> Optional[List[Column]]:
        """Columns of the last query, None for statements without result."""
        return self._description

    @property
    def rowcount(self) -> int:
        """Rows affected by the last update, or returned by the last query.

        -1 while a streamed query has not been read to the end.
        """
        return self._rowcount

    @property
    def rownumber(self) -> Optional[int]:
        """Index of the next row to fetch, None if there is no result."""
        return self._rownumber if self._description is not None else None

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, factory):
        self._row_factory = factory
        if self._description is not None:
            self._make_row = factory(self)

    @property
    def adapters(self):
        return self._conn.adapters

    # -- state ----------------------------------------------------------------

    def _reset(self) -> None:
        self._release()
        self._description: Optional[List[Column]] = None
        self._rowcount = -1
        self._rownumber = 0
        self._cols: List[list] = []      # converted values of the current chunk, by column
        self._nrows = 0                  # rows in the current chunk
        self._rows_cache: Optional[List[tuple]] = None
        self._pos = 0
        self._exhausted = True
        self._delivered = 0
        self._loaders: List[Callable] = []
        self._make_row: Callable = tuple
        self._batch: Optional[int] = None

    def _release(self) -> None:
        rs, stmt = getattr(self, "_rs", None), getattr(self, "_stmt", None)
        self._rs = self._stmt = None
        conn = getattr(self, "_conn", None)
        if conn is None or conn.closed:
            return
        if rs:
            self._lib.close_query(rs)
        if stmt:
            self._lib.close_query(stmt)

    def _check(self) -> None:
        if self._closed:
            raise errors.InterfaceError("the cursor is closed")
        self._conn._check()

    def close(self) -> None:
        """Close the cursor and release the native result."""
        if not self._closed:
            with self._conn._lock:
                self._reset()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # -- execution ------------------------------------------------------------

    def execute(self, query, params=None, *, prepare: Optional[bool] = None) -> "Cursor":
        """Execute a statement; return the cursor itself (chainable)::

            cur.execute("SELECT * FROM t WHERE id = %s", [42]).fetchone()

        Parameters are bound natively (prepared statement); ``prepare=False``
        inlines them as escaped SQL literals instead.
        """
        self._check()
        with self._conn._lock:
            self._reset()
            self._run(query, params, prepare)
        return self

    def executemany(self, query, params_seq, *, prepare: Optional[bool] = None) -> None:
        """Execute a statement once per item of ``params_seq``.

        Meant for INSERT/UPDATE/DELETE: the statement is prepared once and the
        rows are sent in native batches; ``rowcount`` is the total of the update
        counts. Results of queries are discarded.
        """
        self._check()
        sql_text = as_query_string(query, self._conn)
        total = 0
        with self._conn._lock:
            self._reset()
            if not self._use_native(prepare):
                for params in params_seq:
                    self._reset()
                    self._run(sql_text, params, False)
                    if self._description is None:
                        total += max(self._rowcount, 0)
                self._reset()
                self._rowcount = total
                return
            lib, adapters = self._lib, self._conn.adapters
            stmt, stmt_text, pending = None, None, 0
            try:
                for params in params_seq:
                    text, binds = render_binds(sql_text, params, adapters)
                    if text != stmt_text:  # the casts depend on the parameter types
                        if pending:
                            total += lib.execute_batch(stmt)
                            pending = 0
                        if stmt:
                            lib.close_query(stmt)
                            stmt = None
                        self._conn._mark_statement()
                        stmt, stmt_text = lib.prepare(self._conn._handle, text), text
                    for i, (kind, value) in enumerate(binds, 1):
                        lib.bind(stmt, i, kind, value)
                    if is_query(text):
                        lib.close_query(lib.execute_prepared(stmt))
                        continue
                    lib.add_batch(stmt)
                    pending += 1
                    if pending >= EXECUTEMANY_BATCH:
                        total += lib.execute_batch(stmt)
                        pending = 0
                if pending:
                    total += lib.execute_batch(stmt)
            finally:
                if stmt:
                    lib.close_query(stmt)
            self._rowcount = total

    def _use_native(self, prepare: Optional[bool]) -> bool:
        if prepare is None:
            prepare = self._conn.prepare
        return True if prepare is None else bool(prepare)

    def _run(self, query, params, prepare: Optional[bool], batch: Optional[int] = None) -> None:
        sql_text = as_query_string(query, self._conn)
        adapters = self._conn.adapters
        if params is None:
            text, binds = sql_text, None
        elif self._use_native(prepare):
            text, binds = render_binds(sql_text, params, adapters)
        else:
            text, binds = render_literals(sql_text, params, adapters), None
        self._batch = batch
        self._conn._mark_statement()
        lib, guess = self._lib, is_query(text)
        # The statement type is guessed from its first keyword; H2 tells when
        # the guess is wrong (90001: not an update, 90002: not a query).
        if binds is not None:
            self._stmt = lib.prepare(self._conn._handle, text)
            for i, (kind, value) in enumerate(binds, 1):
                lib.bind(self._stmt, i, kind, value)
            run_query = lambda: lib.execute_prepared(self._stmt)  # noqa: E731
            run_update = lambda: lib.execute_prepared_update(self._stmt)  # noqa: E731
        else:
            run_query = lambda: lib.query(self._conn._handle, text)  # noqa: E731
            run_update = lambda: lib.execute(self._conn._handle, text)  # noqa: E731
        if guess:
            try:
                self._rs = run_query()
            except errors.ProgrammingError as exc:
                if exc.h2_code != 90002:
                    raise
                self._rowcount = run_update()
                return
        else:
            try:
                self._rowcount = run_update()
                return
            except errors.ProgrammingError as exc:
                if exc.h2_code != 90001:
                    raise
                self._rs = run_query()
        self._start_result()

    # -- result reading -------------------------------------------------------

    def _start_result(self) -> None:
        meta = self._lib.metadata(self._rs)
        self._exhausted = False
        chunk = self._read_chunk()
        type_names: List[Optional[str]] = [None] * len(chunk.names)
        if len(meta) == len(chunk.names):
            type_names = [m.get("typeName") for m in meta]
        self._description = [Column(n, c, t) for n, c, t in
                             zip(chunk.names, chunk.type_codes, type_names)]
        adapters = self._conn.adapters
        self._loaders = [adapters.loader(c, t) for c, t in zip(chunk.type_codes, type_names)]
        self._make_row = self._row_factory(self)
        self._set_chunk(chunk)

    def _read_chunk(self) -> Chunk:
        if self._batch:
            chunk = decode(self._lib.fetch_batch(self._rs, self._batch))
            self._exhausted = chunk.row_count < self._batch
        else:
            chunk = decode(self._lib.fetch_all(self._rs))
            self._exhausted = True
        return chunk

    def _set_chunk(self, chunk: Chunk) -> None:
        columns = []
        for col, load in zip(chunk.columns, self._loaders):
            if load is _identity:
                columns.append(col)
            elif load is _load_geometry:
                columns.append(load_geometry_column(col))
            else:
                columns.append([None if v is None else load(v) for v in col])
        self._cols = columns
        self._nrows = chunk.row_count
        self._rows_cache = None
        self._pos = 0
        self._delivered += chunk.row_count
        if self._exhausted:
            self._rowcount = self._delivered
            self._release()

    def _rows(self) -> List[tuple]:
        if self._rows_cache is None:
            self._rows_cache = list(zip(*self._cols)) if self._cols else [()] * self._nrows
        return self._rows_cache

    def _fill(self) -> bool:
        """Make sure at least one row is buffered; False at the end."""
        while self._pos >= self._nrows:
            if self._exhausted:
                return False
            self._set_chunk(self._read_chunk())
        return True

    def _check_result(self) -> None:
        self._check()
        if self._description is None:
            raise errors.ProgrammingError("the last operation didn't produce a result")

    def _take(self, size: Optional[int]) -> List[tuple]:
        """Up to ``size`` (None: all) remaining rows as tuples."""
        out: List[tuple] = []
        with self._conn._lock:
            while (size is None or len(out) < size) and self._fill():
                stop = self._nrows if size is None else min(self._nrows, self._pos + size - len(out))
                out.extend(self._rows()[self._pos:stop])
                self._pos = stop
        self._rownumber += len(out)
        return out

    def fetchone(self):
        """Next row, or None at the end."""
        self._check_result()
        rows = self._take(1)
        return self._make_row(rows[0]) if rows else None

    def fetchmany(self, size: Optional[int] = None) -> list:
        """Next ``size`` rows (default :attr:`arraysize`)."""
        self._check_result()
        make = self._make_row
        return [make(r) for r in self._take(self.arraysize if size is None else size)]

    def fetchall(self) -> list:
        """All the remaining rows."""
        self._check_result()
        make = self._make_row
        return [make(r) for r in self._take(None)]

    def __iter__(self) -> Iterator:
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row

    def stream(self, query, params=None, *, size: int = 10000,
               prepare: Optional[bool] = None) -> Iterator:
        """Execute a query and yield its rows, reading ``size`` rows per native call,
        so that big results never sit entirely in memory."""
        self._check()
        with self._conn._lock:
            self._reset()
            self._run(query, params, prepare, batch=size)
        if self._description is None:
            raise errors.ProgrammingError("stream() needs a statement returning rows")
        yield from self

    # -- column access (h2gis extension) ---------------------------------------

    def fetch_columns(self) -> Dict[str, list]:
        """Remaining rows as ``{column name: [values]}``, ready for pandas/GeoPandas.

        Raises ProgrammingError if two columns have the same name (use aliases).
        """
        self._check_result()
        names = [c.name for c in self._description]  # type: ignore[union-attr]
        if len(set(names)) != len(names):
            dup = sorted({n for n in names if names.count(n) > 1})
            raise errors.ProgrammingError(f"duplicate column names {dup}: use aliases")
        return dict(zip(names, self.fetch_column_lists()))

    def fetch_column_lists(self, size: Optional[int] = None) -> List[list]:
        """Up to ``size`` (None: all) remaining rows as one list per column."""
        self._check_result()
        out: List[list] = [[] for _ in self._description]  # type: ignore[union-attr]
        taken = 0
        with self._conn._lock:
            while (size is None or taken < size) and self._fill():
                stop = self._nrows if size is None else min(self._nrows, self._pos + size - taken)
                if self._pos == 0 and stop == self._nrows and not taken:
                    out = [list(c) if c is not None else [] for c in self._cols] or out
                else:
                    for dst, col in zip(out, self._cols):
                        dst.extend(col[self._pos:stop])
                taken += stop - self._pos
                self._pos = stop
        self._rownumber += taken
        return out

    # -- PEP 249 optional methods ----------------------------------------------

    def nextset(self):
        return None

    def setinputsizes(self, sizes: Sequence[Any]) -> None:
        pass

    def setoutputsize(self, size: int, column: Optional[int] = None) -> None:
        pass
