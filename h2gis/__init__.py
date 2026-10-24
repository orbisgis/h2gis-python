"""
* H2GIS-python is a Python wrapper to use H2GIS.
* <a href="http://www.h2database.com">http://www.h2database.com</a>. H2GIS-python is developed by CNRS
* <a href="http://www.cnrs.fr/">http://www.cnrs.fr/</a>.
*
* This code is part of the H2GIS-python project. H2GIS-python is free software;
* you can redistribute it and/or modify it under the terms of the GNU
* Lesser General Public License as published by the Free Software Foundation;
* version 3.0 of the License.
*
* H2GIS-python is distributed in the hope that it will be useful, but
* WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
* FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License
* for more details <http://www.gnu.org/licenses/>.
*
*
* For more information, please consult: <a href="http://www.h2gis.org/">http://www.h2gis.org/</a>
* or contact directly: info_at_h2gis.org

@author Maël PHILIPPE, CNRS
@author Erwan BOCHER, CNRS

DB-API 2.0 driver for H2GIS, with an API modelled on psycopg 3::

    import h2gis
    from h2gis.rows import dict_row

    with h2gis.connect("/data/my_db", row_factory=dict_row) as conn:
        conn.execute("INSERT INTO LIEUX(NOM, THE_GEOM) VALUES (%s, %s)", ["Nantes", point])
        for row in conn.execute("SELECT * FROM LIEUX"):
            print(row["NOM"], row["THE_GEOM"])
        gdf = h2gis.read_gdf(conn, "SELECT * FROM LIEUX")
"""

import datetime as _dt
import time as _time

from . import errors, rows, sql
from .adapt import AdaptersMap, ColumnType, Geometry, Json, adapters
from .connection import Connection, Rollback, Transaction, connect
from .cursor import Column, Cursor
from .dataframe import read_df, read_gdf, to_h2gis
from .errors import (DatabaseError, DataError, Error, IntegrityError, InterfaceError,
                     InternalError, NotSupportedError, OperationalError, ProgrammingError,
                     Warning)

__version__ = "2.0.0"

# --- PEP 249 module interface ------------------------------------------------

apilevel = "2.0"
threadsafety = 2  # threads may share the module and connections (calls are serialized)
paramstyle = "pyformat"


class DBAPITypeObject:
    """Compare equal to the ``type_code`` values of a family of types (PEP 249)."""

    def __init__(self, name: str, *codes: int):
        self.name = name
        self.codes = frozenset(codes)

    def __eq__(self, other) -> bool:
        if isinstance(other, DBAPITypeObject):
            return self.codes == other.codes
        return other in self.codes

    def __hash__(self) -> int:
        return hash(self.codes)

    def __repr__(self) -> str:
        return f"<DBAPITypeObject {self.name}>"


STRING = DBAPITypeObject("STRING", ColumnType.STRING)
BINARY = DBAPITypeObject("BINARY", ColumnType.BINARY)
NUMBER = DBAPITypeObject("NUMBER", ColumnType.INT, ColumnType.LONG, ColumnType.FLOAT,
                         ColumnType.DOUBLE, ColumnType.DECIMAL)
DATETIME = DBAPITypeObject("DATETIME", ColumnType.TEMPORAL)
ROWID = DBAPITypeObject("ROWID")
BOOLEAN = DBAPITypeObject("BOOLEAN", ColumnType.BOOLEAN)
GEOMETRY = DBAPITypeObject("GEOMETRY", ColumnType.GEOMETRY)
JSON = DBAPITypeObject("JSON", ColumnType.JSON)
UUID = DBAPITypeObject("UUID", ColumnType.UUID)

Date = _dt.date
Time = _dt.time
Timestamp = _dt.datetime
Binary = bytes


def DateFromTicks(ticks: float) -> _dt.date:
    return Date(*_time.localtime(ticks)[:3])


def TimeFromTicks(ticks: float) -> _dt.time:
    return Time(*_time.localtime(ticks)[3:6])


def TimestampFromTicks(ticks: float) -> _dt.datetime:
    return Timestamp(*_time.localtime(ticks)[:6])


__all__ = [
    "connect", "Connection", "Cursor", "Column", "Transaction", "Rollback",
    "read_df", "read_gdf", "to_h2gis", "Geometry", "Json", "AdaptersMap", "adapters",
    "errors", "rows", "sql",
    "apilevel", "threadsafety", "paramstyle",
    "Warning", "Error", "InterfaceError", "DatabaseError", "DataError", "OperationalError",
    "IntegrityError", "InternalError", "ProgrammingError", "NotSupportedError",
    "STRING", "BINARY", "NUMBER", "DATETIME", "ROWID", "BOOLEAN", "GEOMETRY", "JSON", "UUID",
    "Date", "Time", "Timestamp", "Binary", "DateFromTicks", "TimeFromTicks",
    "TimestampFromTicks",
]
