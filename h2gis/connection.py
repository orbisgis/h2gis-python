"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Connection and transaction management, following psycopg 3:

* not in autocommit by default: the first statement starts a transaction,
  ``commit()``/``rollback()`` end it;
* ``with h2gis.connect(...) as conn:`` commits on success, rolls back on
  error, then closes the connection;
* ``with conn.transaction():`` blocks can be nested (savepoints);
  ``raise h2gis.Rollback`` inside a block rolls it back silently.

H2 specific: DDL statements (CREATE, DROP, ALTER...) commit the current
transaction implicitly.
"""

from __future__ import annotations

import atexit
import os
import re
import threading
import weakref
from typing import Any, Callable, List, Optional, Union

from . import errors
from ._native import NativeLib, get_lib
from .adapt import AdaptersMap, adapters as global_adapters
from .cursor import Cursor
from .rows import tuple_row

__all__ = ["Connection", "Transaction", "Rollback", "connect"]

_OPEN_CONNECTIONS: "weakref.WeakSet[Connection]" = weakref.WeakSet()

_URL_PREFIX_RE = re.compile(
    r"^(?:mem:|file:|tcp:|ssl:|zip:|nio\w*:|split:|async:|retry:|memFS:|memLZF:"
    r"|/|\./|\.\./|~|[A-Za-z]:[\\/]|\\\\|\.\\|\.\.\\)")


def _normalize_path(path: Union[str, "os.PathLike[str]"]) -> str:
    """Make a database path acceptable by ``jdbc:h2:``.

    * ``data/my_db`` -> ``./data/my_db`` (H2 2.x refuses implicitly relative paths)
    * ``my_db.mv.db`` -> ``my_db`` (H2 adds the extension itself)
    URL options after ``;`` are kept.
    """
    text = os.fspath(path)
    if not text:
        raise errors.InterfaceError("empty database path")
    base, sep, options = text.partition(";")
    if base.endswith(".mv.db"):
        base = base[:-len(".mv.db")]
    if not _URL_PREFIX_RE.match(base):
        base = "./" + base
    return base + sep + options


class Rollback(Exception):
    """Raise inside ``with conn.transaction()`` to roll the block back silently.

    ``Rollback(tx)`` rolls back up to the enclosing block ``tx``.
    """

    def __init__(self, transaction: Optional["Transaction"] = None):
        super().__init__(transaction)
        self.transaction = transaction


class Transaction:
    """A transaction block, created by :meth:`Connection.transaction`."""

    def __init__(self, conn: "Connection", savepoint_name: Optional[str] = None,
                 force_rollback: bool = False):
        self.connection = conn
        self.savepoint_name = savepoint_name
        self.force_rollback = force_rollback
        self._kind: Optional[str] = None  # "autocommit" | "begin" | "savepoint"

    def __repr__(self) -> str:
        return f"<Transaction {self._kind or 'inactive'} {self.savepoint_name or ''}>".strip()

    def __enter__(self) -> "Transaction":
        conn = self.connection
        conn._check()
        with conn._lock:
            if not conn._tx_stack:
                if conn._autocommit:
                    self._kind = "autocommit"
                    conn._exec("SET AUTOCOMMIT FALSE")
                elif not conn._in_tx:
                    self._kind = "begin"
                else:
                    self._kind = "savepoint"
            else:
                self._kind = "savepoint"
            if self._kind == "savepoint":
                if not self.savepoint_name:
                    self.savepoint_name = f"_h2gis_sp_{len(conn._tx_stack) + 1}"
                conn._exec(f"SAVEPOINT {_quote_ident(self.savepoint_name)}")
            conn._tx_stack.append(self)
            conn._in_tx = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        conn = self.connection
        with conn._lock:
            if conn._tx_stack and conn._tx_stack[-1] is self:
                conn._tx_stack.pop()
            if conn.closed:
                return False
            commit = exc_type is None and not self.force_rollback
            try:
                self._finish(commit)
            except Exception as finish_exc:
                if exc_type is None or isinstance(exc, Rollback):
                    # A requested rollback that fails must not pass silently.
                    # Typical cause: a DDL statement inside the block committed
                    # the transaction and invalidated the savepoint (H2 90063).
                    raise errors.OperationalError(
                        f"the transaction block could not be {'committed' if commit else 'rolled back'}"
                        f": {finish_exc} (DDL statements commit the transaction in H2)",
                        h2_code=getattr(finish_exc, "h2_code", None),
                        sqlstate=getattr(finish_exc, "sqlstate", None)) from finish_exc
                # otherwise keep the original exception, the rollback error is secondary
            if isinstance(exc, Rollback):
                return exc.transaction is None or exc.transaction is self
            return False

    def _finish(self, commit: bool) -> None:
        conn = self.connection
        if self._kind == "savepoint":
            name = _quote_ident(self.savepoint_name or "")
            if not commit:
                conn._exec(f"ROLLBACK TO SAVEPOINT {name}")
            conn._exec(f"RELEASE SAVEPOINT {name}")
            return
        try:
            conn._exec("COMMIT" if commit else "ROLLBACK")
        finally:
            conn._in_tx = False
            if self._kind == "autocommit":
                conn._exec("SET AUTOCOMMIT TRUE")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class Connection:
    """A connection to an H2GIS database, created by :func:`connect`."""

    def __init__(self, lib: NativeLib, handle: int, path: str, *,
                 autocommit: bool, row_factory: Callable, prepare: Optional[bool]):
        self._lib = lib
        self._handle = handle
        self._path = path
        self._lock = threading.RLock()
        self._closed = False
        self._autocommit = True
        self._in_tx = False
        self._tx_stack: List[Transaction] = []
        self.row_factory = row_factory
        self.prepare = prepare
        """Default of ``execute(prepare=...)``: None = native binding when available."""
        self.adapters = AdaptersMap(global_adapters)
        """Per connection copy of :data:`h2gis.adapters`."""
        if not autocommit:
            self._exec("SET AUTOCOMMIT FALSE")
            self._autocommit = False
        _OPEN_CONNECTIONS.add(self)

    @classmethod
    def connect(cls, conninfo: Union[str, "os.PathLike[str]"] = "mem:", user: str = "sa",
                password: str = "", *, autocommit: bool = False,
                row_factory: Optional[Callable] = None, prepare: Optional[bool] = None,
                lib_path: Optional[str] = None) -> "Connection":
        """Open a database. See :func:`h2gis.connect`."""
        lib = get_lib(lib_path)
        path = _normalize_path(conninfo)
        handle = lib.connect(path, user, password)
        try:
            return cls(lib, handle, path, autocommit=autocommit,
                       row_factory=row_factory or tuple_row, prepare=prepare)
        except BaseException:
            lib.close_connection(handle)
            raise

    # -- info -----------------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def broken(self) -> bool:
        return False

    @property
    def path(self) -> str:
        """The database path, as passed to ``jdbc:h2:``."""
        return self._path

    @property
    def native_version(self) -> int:
        """Version of the C interface of the native library (``h2gis_version()``)."""
        return self._lib.version

    @property
    def lib_path(self) -> str:
        """Path of the native library."""
        return self._lib.path

    def __repr__(self) -> str:
        state = "closed" if self._closed else ("autocommit" if self._autocommit else "transactional")
        return f"<h2gis.Connection {self._path!r} {state}>"

    # -- internal -------------------------------------------------------------

    def _check(self) -> None:
        if self._closed:
            raise errors.InterfaceError("the connection is closed")

    def _exec(self, sql: str) -> int:
        return self._lib.execute(self._handle, sql)

    def _mark_statement(self) -> None:
        if not self._autocommit:
            self._in_tx = True

    # -- psycopg 3 API --------------------------------------------------------

    @property
    def autocommit(self) -> bool:
        return self._autocommit

    @autocommit.setter
    def autocommit(self, value: bool) -> None:
        self._check()
        value = bool(value)
        if value == self._autocommit:
            return
        with self._lock:
            if self._in_tx or self._tx_stack:
                raise errors.ProgrammingError(
                    "can't change autocommit now: the connection is in a transaction; "
                    "call commit() or rollback() first")
            self._exec("SET AUTOCOMMIT TRUE" if value else "SET AUTOCOMMIT FALSE")
            self._autocommit = value

    def cursor(self, *, row_factory: Optional[Callable] = None) -> Cursor:
        self._check()
        return Cursor(self, row_factory=row_factory)

    def execute(self, query, params=None, *, prepare: Optional[bool] = None) -> Cursor:
        """Shortcut for ``conn.cursor().execute(query, params)``."""
        return self.cursor().execute(query, params, prepare=prepare)

    def commit(self) -> None:
        self._check()
        with self._lock:
            if self._tx_stack:
                raise errors.ProgrammingError(
                    "explicit commit() forbidden within a Transaction context "
                    "(transaction blocks commit automatically)")
            if not self._autocommit:
                self._exec("COMMIT")
            self._in_tx = False

    def rollback(self) -> None:
        self._check()
        with self._lock:
            if self._tx_stack:
                raise errors.ProgrammingError(
                    "explicit rollback() forbidden within a Transaction context "
                    "(raise h2gis.Rollback instead)")
            if not self._autocommit:
                self._exec("ROLLBACK")
            self._in_tx = False

    def transaction(self, savepoint_name: Optional[str] = None,
                    force_rollback: bool = False) -> Transaction:
        """Start a transaction block (a savepoint if one is already running)::

            with conn.transaction():
                conn.execute("INSERT ...")
        """
        return Transaction(self, savepoint_name, force_rollback)

    def close(self) -> None:
        """Close the connection. An uncommitted transaction is rolled back."""
        if self._closed:
            return
        with self._lock:
            self._closed = True
            _OPEN_CONNECTIONS.discard(self)
            self._lib.close_connection(self._handle)

    def delete_database(self) -> None:
        """Drop all the objects, delete the database files and close the connection."""
        self._check()
        with self._lock:
            self._closed = True
            _OPEN_CONNECTIONS.discard(self)
            self._lib.delete_database_and_close(self._handle)

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._closed:
            return
        try:
            if not self._tx_stack:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            self.close()

    def __del__(self):
        try:
            if not self._closed:
                self.close()
        except Exception:
            pass

    # -- PEP 249 exceptions as attributes (optional extension) ---------------

    Warning = errors.Warning
    Error = errors.Error
    InterfaceError = errors.InterfaceError
    DatabaseError = errors.DatabaseError
    DataError = errors.DataError
    OperationalError = errors.OperationalError
    IntegrityError = errors.IntegrityError
    InternalError = errors.InternalError
    ProgrammingError = errors.ProgrammingError
    NotSupportedError = errors.NotSupportedError


def connect(conninfo: Union[str, "os.PathLike[str]"] = "mem:", user: str = "sa",
            password: str = "", *, autocommit: bool = False,
            row_factory: Optional[Callable] = None, prepare: Optional[bool] = None,
            lib_path: Optional[str] = None) -> Connection:
    """Open an H2GIS database.

    Parameters
    ----------
    conninfo:
        Database path as understood by ``jdbc:h2:`` (``/data/my_db``,
        ``./my_db``, ``mem:test``, URL options after ``;``). A relative path
        without ``./`` is accepted; a trailing ``.mv.db`` is removed.
    user, password:
        Credentials (``sa`` / empty by default).
    autocommit:
        False (default) like psycopg: statements run in a transaction that
        must be committed.
    row_factory:
        Default row factory of the cursors (:mod:`h2gis.rows`).
    prepare:
        Default parameter binding mode: None (native binding when the library
        supports it), True (require it) or False (client side literals).
    lib_path:
        Native library to use (default: ``$H2GIS_LIB_PATH`` or the bundled one).
    """
    return Connection.connect(conninfo, user, password, autocommit=autocommit,
                              row_factory=row_factory, prepare=prepare, lib_path=lib_path)


@atexit.register
def _close_all() -> None:  # pragma: no cover - process exit
    for conn in list(_OPEN_CONNECTIONS):
        try:
            conn.close()
        except Exception:
            pass
