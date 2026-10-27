"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

DB-API 2.0 exception hierarchy, modelled on ``psycopg.errors``.

Native errors carry the H2 error code at the end of the message, e.g.
``... SELECT * FROM NOPE [42102-232]``. :func:`from_native_message` parses it
and returns an instance of the most specific class (``UndefinedTable`` for
42102, ``UniqueViolation`` for 23505, ...), so you can write::

    try:
        conn.execute("SELECT * FROM missing")
    except h2gis.errors.UndefinedTable:
        ...
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Type

__all__ = [
    "Warning", "Error", "InterfaceError", "DatabaseError", "DataError",
    "OperationalError", "IntegrityError", "InternalError", "ProgrammingError",
    "NotSupportedError",
    # specific classes
    "UndefinedTable", "UndefinedColumn", "UndefinedFunction", "DuplicateTable",
    "DuplicateColumn", "SyntaxError", "UniqueViolation", "ForeignKeyViolation",
    "NotNullViolation", "CheckViolation", "InvalidTextRepresentation",
    "NumericValueOutOfRange", "DivisionByZero", "StringDataRightTruncation",
    "LockNotAvailable", "SerializationFailure", "DatabaseAlreadyOpen",
    "DatabaseNotFound", "FetchError",
    "lookup", "from_native_message",
]


class Warning(Exception):  # noqa: A001 - name imposed by PEP 249
    """Important warnings (PEP 249)."""


class Error(Exception):
    """Base class of all the errors raised by h2gis (PEP 249).

    Attributes
    ----------
    h2_code:
        The numeric H2 error code (``42102``...), or ``None``.
    sqlstate:
        The 5 characters SQLSTATE derived from the H2 code, or ``None``.
    raw_message:
        The message as returned by the native library.
    """

    def __init__(self, *args, h2_code: Optional[int] = None,
                 sqlstate: Optional[str] = None, raw_message: Optional[str] = None):
        super().__init__(*args)
        self.h2_code = h2_code
        self.sqlstate = sqlstate
        self.raw_message = raw_message


class InterfaceError(Error):
    """Error related to the interface rather than the database (PEP 249)."""


class DatabaseError(Error):
    """Error related to the database (PEP 249)."""


class DataError(DatabaseError):
    """Problem with the processed data: conversion, out of range... (PEP 249)."""


class OperationalError(DatabaseError):
    """Error related to the database operation: lock, file, connection (PEP 249)."""


class IntegrityError(DatabaseError):
    """Relational integrity violated: unique key, foreign key... (PEP 249)."""


class InternalError(DatabaseError):
    """Internal error of the database (PEP 249)."""


class ProgrammingError(DatabaseError):
    """Programming error: table not found, syntax error, wrong parameters (PEP 249)."""


class NotSupportedError(DatabaseError):
    """Method or feature not supported by the database or the native library (PEP 249)."""


# --- specific classes (names follow psycopg.errors where possible) ---------

class UndefinedTable(ProgrammingError):
    pass


class UndefinedColumn(ProgrammingError):
    pass


class UndefinedFunction(ProgrammingError):
    pass


class DuplicateTable(ProgrammingError):
    pass


class DuplicateColumn(ProgrammingError):
    pass


class SyntaxError(ProgrammingError):  # noqa: A001 - same name as psycopg.errors.SyntaxError
    pass


class UniqueViolation(IntegrityError):
    pass


class ForeignKeyViolation(IntegrityError):
    pass


class NotNullViolation(IntegrityError):
    pass


class CheckViolation(IntegrityError):
    pass


class InvalidTextRepresentation(DataError):
    """A value could not be converted (H2 ``22018``)."""


class NumericValueOutOfRange(DataError):
    pass


class DivisionByZero(DataError):
    pass


class StringDataRightTruncation(DataError):
    pass


class LockNotAvailable(OperationalError):
    """Lock timeout (H2 ``50200``)."""


class SerializationFailure(OperationalError):
    """Deadlock or transaction conflict (H2 ``40001``)."""


class DatabaseAlreadyOpen(OperationalError):
    """The database file is locked by another process (H2 ``90020``)."""


class DatabaseNotFound(OperationalError):
    """The database does not exist (H2 ``90013``/``90146``)."""


class FetchError(DatabaseError):
    """The native library failed to serialize a result set."""


# H2 error code -> exception class
_BY_CODE: Dict[int, Type[Error]] = {
    42101: DuplicateTable,
    42102: UndefinedTable,
    42103: UndefinedTable,
    42104: UndefinedTable,
    42121: DuplicateColumn,
    42122: UndefinedColumn,
    42000: SyntaxError,
    42001: SyntaxError,
    90022: UndefinedFunction,
    23505: UniqueViolation,
    23503: ForeignKeyViolation,
    23506: ForeignKeyViolation,
    23502: NotNullViolation,
    23513: CheckViolation,
    23514: CheckViolation,
    22018: InvalidTextRepresentation,
    22003: NumericValueOutOfRange,
    22012: DivisionByZero,
    22001: StringDataRightTruncation,
    50200: LockNotAvailable,
    40001: SerializationFailure,
    90131: SerializationFailure,
    90020: DatabaseAlreadyOpen,
    90013: DatabaseNotFound,
    90146: DatabaseNotFound,
    90001: ProgrammingError,  # executeUpdate on a query
    90002: ProgrammingError,  # executeQuery on an update
    90008: DataError,         # invalid value for parameter
    90012: ProgrammingError,  # parameter not set
    90046: InterfaceError,    # URL format error
    90028: OperationalError,  # IO exception
    90098: OperationalError,  # database closed
    90121: OperationalError,  # database closed by VM shutdown
}

# H2 codes whose SQLSTATE is not the code itself (org.h2.api.ErrorCode#getState)
_STATE_BY_CODE = {
    42101: "42S01", 42102: "42S02", 42103: "42S02", 42104: "42S04",
    42121: "42S21", 42122: "42S22", 50200: "HYT00",
}

# SQLSTATE class -> exception class
_BY_CLASS = {
    "08": OperationalError,
    "22": DataError,
    "23": IntegrityError,
    "40": OperationalError,
    "42": ProgrammingError,
    "HY": OperationalError,
}

_CODE_RE = re.compile(r"\[(\d{5})-\d+\]\s*$")
_PREFIX_RE = re.compile(r"^(Failed to [^:]*|[A-Z][a-z]+ [a-z ]+failed): ")


def lookup(h2_code: Optional[int]) -> Type[Error]:
    """Return the exception class associated with an H2 error code."""
    if h2_code is None:
        return DatabaseError
    cls = _BY_CODE.get(h2_code)
    if cls is not None:
        return cls
    state = _STATE_BY_CODE.get(h2_code, str(h2_code))
    return _BY_CLASS.get(state[:2], DatabaseError)


def from_native_message(message: str, default: Type[Error] = DatabaseError) -> Error:
    """Build the right exception from a message returned by ``h2gis_get_last_error``."""
    message = (message or "").strip()
    match = _CODE_RE.search(message)
    code = int(match.group(1)) if match else None
    cls = lookup(code) if code is not None else default
    sqlstate = _STATE_BY_CODE.get(code, str(code)) if code is not None else None
    # Drop the "Failed to execute query: " prefix added by the C interface and,
    # when H2 runs with a non English locale, the localized first line.
    text = _PREFIX_RE.sub("", message)
    lines = text.split("\n")
    if (code is not None and len(lines) > 1 and "; SQL statement:" not in lines[0]
            and not _CODE_RE.search(lines[0])
            and ("; SQL statement:" in lines[1] or _CODE_RE.search(lines[1]))):
        # "<localized>\n<english>; SQL statement:\n<sql> [code-ver]"
        text = "\n".join(lines[1:])
    return cls(text or "unknown native error", h2_code=code, sqlstate=sqlstate,
               raw_message=message)
