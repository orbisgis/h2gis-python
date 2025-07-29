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
"""

import ctypes
import os
import platform
import ast
import json
import sys
import struct
from typing import List, Dict, Union, Optional
from enum import IntEnum
from shapely import wkb
from shapely.geometry.base import BaseGeometry


class ColumnType(IntEnum):
    """
    Enumeration of supported SQL column types used for result deserialization.
    """
    INT = 1
    LONG = 2
    FLOAT = 3
    DOUBLE = 4
    BOOLEAN = 5
    STRING = 6
    DATE = 7
    GEOMETRY = 8
    OTHER = 99


# Empty structs to represent GraalVM isolate types
class GraalIsolate(ctypes.Structure):
    _fields_ = []


class GraalIsolateThread(ctypes.Structure):
    _fields_ = []


class GraalIsolateParams(ctypes.Structure):
    _fields_ = []


GraalIsolate_p = ctypes.POINTER(GraalIsolate)
GraalIsolateThread_p = ctypes.POINTER(GraalIsolateThread)


class H2GIS:
    """
    Python wrapper for a native H2GIS database compiled with GraalVM.
    This class provides methods to connect to the database, execute queries,
    and fetch typed results using ctypes to interface with the C shared library.
    """

    def __init__(self, db_path=None, username="sa", password="", lib_path=None):
        """
        Initialize the H2GIS wrapper, create GraalVM isolate and optionally connect to the DB.
        """
        if lib_path is None:
            lib_path = self._default_library_path()

        self.lib = ctypes.CDLL(lib_path)
        self._setup_c_function_signatures()

        self.isolate = GraalIsolate_p()
        self.thread = GraalIsolateThread_p()
        self._connection = ctypes.c_long(0)

        params = GraalIsolateParams()
        if self.lib.graal_create_isolate(
                ctypes.byref(params), ctypes.byref(self.isolate), ctypes.byref(self.thread)
        ) != 0:
            raise RuntimeError("Failed to create GraalVM isolate")

        if db_path is not None:
            self.connect(db_path, username, password)

    def _default_library_path(self):
        """
        Determine the default shared library path based on the OS.
        """
        base_dir = os.path.dirname(__file__)
        system = platform.system()
        libname = "h2gis.dll" if system == "Windows" else "h2gis.so"
        return os.path.join(base_dir, "lib", libname)

    def _setup_c_function_signatures(self):
        """
        Define the argument and return types for all C functions used.
        """
        self.lib.graal_create_isolate.argtypes = [
            ctypes.POINTER(GraalIsolateParams),
            ctypes.POINTER(GraalIsolate_p),
            ctypes.POINTER(GraalIsolateThread_p),
        ]
        self.lib.graal_create_isolate.restype = ctypes.c_int

        self.lib.graal_tear_down_isolate.argtypes = [GraalIsolateThread_p]
        self.lib.graal_tear_down_isolate.restype = ctypes.c_int

        self.lib.h2gis_connect.argtypes = [
            GraalIsolateThread_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_char_p,
        ]
        self.lib.h2gis_connect.restype = ctypes.c_long

        self.lib.h2gis_execute.argtypes = [
            GraalIsolateThread_p,
            ctypes.c_long,
            ctypes.c_char_p,
        ]
        self.lib.h2gis_execute.restype = ctypes.c_int

        self.lib.h2gis_fetch.argtypes = [
            GraalIsolateThread_p, ctypes.c_long, ctypes.c_char_p
        ]
        self.lib.h2gis_fetch.restype = ctypes.c_long

        self.lib.h2gis_fetch_all.argtypes = [
            GraalIsolateThread_p,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        self.lib.h2gis_fetch_all.restype = ctypes.c_void_p

        self.lib.h2gis_fetch_one.argtypes = [
            GraalIsolateThread_p,
            ctypes.c_long,
            ctypes.c_void_p,
        ]
        self.lib.h2gis_fetch_one.restype = ctypes.c_void_p

        self.lib.h2gis_free_result_set.argtypes = [GraalIsolateThread_p, ctypes.c_long]
        self.lib.h2gis_free_result_set.restype = ctypes.c_long

        self.lib.h2gis_free_result_buffer.argtypes = [GraalIsolateThread_p, ctypes.c_void_p]
        self.lib.h2gis_free_result_buffer.restype = None

        self.lib.h2gis_close_connection.argtypes = [GraalIsolateThread_p, ctypes.c_long]
        self.lib.h2gis_close_connection.restype = None

        self.lib.h2gis_delete_database_and_close.argtypes = [GraalIsolateThread_p, ctypes.c_long]
        self.lib.h2gis_delete_database_and_close.restype = None

        self.lib.h2gis_get_column_types.argtypes = [GraalIsolateThread_p, ctypes.c_long, ctypes.c_void_p]
        self.lib.h2gis_get_column_types.restype = ctypes.c_void_p

    def connect(self, dbPath: str, username="sa", password=""):
        """
        Connect to the H2GIS database with the given path and credentials.
        """
        if not dbPath:
            raise ValueError("dbPath should not be None")

        self._connection = self.lib.h2gis_connect(
            self.thread,
            dbPath.encode("utf-8"),
            username.encode("utf-8"),
            password.encode("utf-8"),
        )

        if self._connection == 0:
            raise RuntimeError("Failed to connect to H2GIS database.")

    def execute(self, sql: str) -> int:
        """
        Execute a SQL statement (INSERT, UPDATE, DELETE, etc.)
        """
        if not self._connection:
            raise RuntimeError("No active database connection.")
        return self.lib.h2gis_execute(self.thread, self._connection, sql.encode("utf-8"))

    def commit(self) -> int:
        """
        Commit the current transaction.
        """
        return self.execute("COMMIT;")

    def rollback(self) -> int:
        """
        Rollback the current transaction.
        """
        return self.execute("ROLLBACK;")

    def fetch(self, query: str, row_index: int = 1, stringformat="utf-8"):
        """
        Execute a SELECT query and return the full result set.
        """
        data_ptr = 0

        try:
            query_bytes = query.encode("utf-8")
            query_handle = self.lib.h2gis_fetch(self.thread, self._connection, query_bytes)

            if query_handle == 0:
                raise RuntimeError("h2gis_fetch failed to return a valid query handle")

            buffer_size = ctypes.c_long(0)

            # Fetch all result rows in binary form
            data_ptr = self.lib.h2gis_fetch_all(self.thread, query_handle, ctypes.byref(buffer_size))
            buf_size = buffer_size.value

            if not data_ptr or buf_size == 0:
                return []

            data_bytes = ctypes.string_at(data_ptr, buf_size)

            # Deserialize raw binary resultset into Python data
            result = self.deserialize_resultset_buffer(data_bytes)
            return result

        finally:
            if data_ptr:
                self.lib.h2gis_free_result_buffer(self.thread, data_ptr)

    def parse_string_buffer(self, buf: bytes, num_rows: int) -> list[str | None]:
        """
        Parse a buffer of null-terminated or length-prefixed strings.
        """
        NULL_LENGTH = 0xFFFFFFFF
        result = []
        offset = 0

        for i in range(num_rows):
            if offset + 4 > len(buf):
                raise ValueError(f"Unexpected end of buffer while reading string length at row {i}")
            length = struct.unpack_from('<I', buf, offset)[0]
            offset += 4

            if length == NULL_LENGTH:
                result.append(None)
                continue

            if offset + length > len(buf):
                raise ValueError(f"Unexpected end of buffer while reading string data at row {i}")

            s = buf[offset:offset + length].decode('utf-8', errors='replace')
            result.append(s)
            offset += length

        return result

    def parse_geometry_buffer(self, buf: bytes, num_rows: int) -> List[Optional[BaseGeometry]]:
        """
        Parse a buffer of length-prefixed WKB geometries and return Shapely geometry objects.
        """
        NULL_LENGTH = 0xFFFFFFFF
        result = []
        offset = 0
        for i in range(num_rows):
            if offset + 4 > len(buf):
                raise ValueError(f"Unexpected end of buffer while reading WKB length at row {i}")
            length = struct.unpack_from('<I', buf, offset)[0]
            offset += 4

            if length == NULL_LENGTH:
                result.append(None)
                continue

            if offset + length > len(buf):
                raise ValueError(f"Unexpected end of buffer while reading WKB data at row {i}")

            geom_bytes = buf[offset:offset + length]
            try:
                geom = wkb.loads(geom_bytes)  # Return the actual Shapely geometry object
                result.append(geom)
            except Exception as e:
                raise ValueError(f"Failed to parse WKB at row {i}: {e}")

            offset += length

        return result

    def isConnected(self) -> bool:
        """
        Return True if the DB connection is active and responsive.
        """
        return (self._connection != 0) and self.ping()

    def ping(self) -> bool:
        """
        Ping the database by executing a basic query.
        """
        try:
            self.fetch("SELECT 1;")
            return True
        except Exception:
            return False

    def close(self):
        """
        Close the current connection (but keep the isolate active).
        """
        if self._connection:
            self.lib.h2gis_close_connection(self.thread, self._connection)
            self._connection = 0

    def deleteAndClose(self):
        """
        Delete the database file and close the connection.
        """
        if self._connection:
            self.lib.h2gis_delete_database_and_close(self.thread, self._connection)
            self._connection = 0

    def __del__(self):
        """
        Destructor – closes DB and tears down the isolate.
        """
        try:
            self.close()
        except Exception:
            pass
        try:
            self.lib.graal_tear_down_isolate(self.thread)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        self.lib.graal_tear_down_isolate(self.thread)

    def deserialize_resultset_buffer(self, buf: bytes) -> dict[str, list]:
        """
        Deserialize the binary buffer returned by `fetch_all` into a typed Python dictionary.
        Each key is a column name and value is a list of column values.
        """
        view = memoryview(buf)
        offset = 0

        col_count = struct.unpack_from("<I", view, offset)[0]
        offset += 4
        row_count = struct.unpack_from("<I", view, offset)[0]
        offset += 4

        # Offsets to column blocks
        col_offsets = [struct.unpack_from("<Q", view, offset + i * 8)[0] for i in range(col_count)]
        offset += col_count * 8

        result = {}
        for col_offset in col_offsets:
            col_view = view[col_offset:]

            name_len = struct.unpack_from("<I", col_view, 0)[0]
            o = 4
            name = col_view[o:o + name_len].tobytes().decode("utf-8")
            o += name_len

            type_code = struct.unpack_from("<I", col_view, o)[0]
            o += 4

            val_buf_size = struct.unpack_from("<I", col_view, o)[0]
            o += 4

            val_buf = col_view[o:o + val_buf_size].tobytes()

            # Dispatch based on column type
            if type_code == ColumnType.INT:
                values = list(struct.unpack_from(f"<{row_count}i", val_buf))
            elif type_code == ColumnType.LONG:
                values = list(struct.unpack_from(f"<{row_count}q", val_buf))
            elif type_code == ColumnType.FLOAT:
                values = list(struct.unpack_from(f"<{row_count}f", val_buf))
            elif type_code == ColumnType.DOUBLE:
                values = list(struct.unpack_from(f"<{row_count}d", val_buf))
            elif type_code == ColumnType.BOOLEAN:
                values = [bool(b) for b in val_buf[:row_count]]
            elif type_code == ColumnType.GEOMETRY:
                values = self.parse_geometry_buffer(val_buf, row_count)
            elif type_code in (ColumnType.STRING, ColumnType.DATE, ColumnType.OTHER, ColumnType.GEOMETRY):
                values = self.parse_string_buffer(val_buf, row_count)
            else:
                raise ValueError(f"Unsupported SQL type code: {type_code}")

            result[name] = values

        return result

    def _fast_parse_length_prefixed_strings(self, view: memoryview, num_rows: int) -> list[str | None]:
        """
        Efficiently parse length-prefixed UTF-8 strings from a memoryview.
        """
        NULL_LENGTH = 0xFFFFFFFF
        out = []
        offset = 0

        for _ in range(num_rows):
            length = struct.unpack_from('<I', view, offset)[0]
            offset += 4

            if length == NULL_LENGTH:
                out.append(None)
                continue

            s = view[offset:offset + length].tobytes().decode('utf-8', errors='replace')
            out.append(s)
            offset += length

        return out

    def _fast_parse_length_prefixed_bytes(view: memoryview, num_rows: int) -> list[bytes]:
        """
        Efficiently parse length-prefixed byte strings from a memoryview.
        """
        out = []
        offset = 0

        for _ in range(num_rows):
            length = struct.unpack_from('<I', view, offset)[0]
            offset += 4
            b = view[offset:offset + length].tobytes()
            out.append(b)
            offset += length

        return out


def read_int32(view: memoryview, offset: int) -> int:
    """Helper function to read 32-bit integer from a memoryview."""
    return struct.unpack_from('<i', view, offset)[0]


def read_int64(view: memoryview, offset: int) -> int:
    """Helper function to read 64-bit integer from a memoryview."""
    return struct.unpack_from('<q', view, offset)[0]
