"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Low level binding to the GraalVM native library (``h2gis.so`` / ``.dll`` /
``.dylib``) built from ``org.h2gis.graalvm.GraalCInterface`` (module
``h2gis-graalvm`` of H2GIS).

* The library must implement the C API version 2 or later
  (``h2gis_version()``); see docs/NATIVE_API.md.
* One GraalVM isolate per library and per process, shared by every connection.
* Each Python thread gets its own isolate thread (``graal_attach_thread``),
  detached when the thread ends: calling into an isolate with the isolate
  thread of another OS thread is undefined behaviour, and the Java side keeps
  the last error per thread.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import threading
from typing import Dict, List, Optional

from . import errors

__all__ = ["NativeLib", "get_lib", "default_library_path", "native_platform",
           "library_file_name", "MIN_C_API_VERSION"]

#: Oldest version of the C interface this driver works with.
MIN_C_API_VERSION = 2


class _GraalIsolate(ctypes.Structure):
    _fields_: list = []


class _GraalIsolateThread(ctypes.Structure):
    _fields_: list = []


_Isolate_p = ctypes.POINTER(_GraalIsolate)
_Thread_p = ctypes.POINTER(_GraalIsolateThread)

# Java long is 64 bits; C long is only 32 bits on Windows (LLP64)
_jlong = ctypes.c_int64
_jint = ctypes.c_int32
_c_char_p = ctypes.c_char_p
_c_void_p = ctypes.c_void_p

# name -> (argtypes, restype). The isolate thread is always the first argument.
_FUNCTIONS = {
    "h2gis_version": ([_Thread_p], _jint),
    "h2gis_get_last_error": ([_Thread_p], _c_void_p),
    "h2gis_free_result_buffer": ([_Thread_p, _c_void_p], None),
    "h2gis_connect": ([_Thread_p, _c_char_p, _c_char_p, _c_char_p], _jlong),
    "h2gis_load": ([_Thread_p, _jlong], _jlong),
    "h2gis_close_connection": ([_Thread_p, _jlong], None),
    "h2gis_delete_database_and_close": ([_Thread_p, _jlong], None),
    "h2gis_execute": ([_Thread_p, _jlong, _c_char_p], _jint),
    "h2gis_fetch": ([_Thread_p, _jlong, _c_char_p], _jlong),
    "h2gis_prepare": ([_Thread_p, _jlong, _c_char_p], _jlong),
    "h2gis_bind_long": ([_Thread_p, _jlong, _jint, _jlong], _jint),
    "h2gis_bind_double": ([_Thread_p, _jlong, _jint, ctypes.c_double], _jint),
    "h2gis_bind_string": ([_Thread_p, _jlong, _jint, _c_char_p], _jint),
    "h2gis_bind_blob": ([_Thread_p, _jlong, _jint, _c_char_p, _jint], _jint),
    "h2gis_bind_null": ([_Thread_p, _jlong, _jint], _jint),
    "h2gis_execute_prepared": ([_Thread_p, _jlong], _jlong),
    "h2gis_execute_prepared_update": ([_Thread_p, _jlong], _jint),
    "h2gis_add_batch": ([_Thread_p, _jlong], _jint),
    "h2gis_execute_batch": ([_Thread_p, _jlong], _jlong),
    "h2gis_close_query": ([_Thread_p, _jlong], None),
    "h2gis_fetch_all": ([_Thread_p, _jlong, _c_void_p], _c_void_p),
    "h2gis_fetch_batch": ([_Thread_p, _jlong, _jint, _c_void_p], _c_void_p),
    "h2gis_get_metadata_json": ([_Thread_p, _jlong], _c_void_p),
}


_LIB_NAMES = {"Windows": "h2gis.dll", "Darwin": "h2gis.dylib"}


def native_platform() -> str:
    """Name of the current platform in the ``native/`` folder: ``linux-x86_64``,
    ``windows-x86_64``, ``macos-arm64``..."""
    system = {"Darwin": "macos"}.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    machine = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64" if system == "macos" else "aarch64"
               }.get(machine, machine)
    return f"{system}-{machine}"


def library_file_name() -> str:
    """``h2gis.so``, ``h2gis.dll`` or ``h2gis.dylib``."""
    return _LIB_NAMES.get(platform.system(), "h2gis.so")


def default_library_path() -> str:
    """Path of the native library, the first of:

    1. ``$H2GIS_LIB_PATH``;
    2. ``h2gis/lib/h2gis.<ext>``, inside an installed wheel;
    3. ``native/<platform>/h2gis.<ext>`` of the repository, when h2gis is used
       from a clone (``pip install -e .``, tests).
    """
    env = os.environ.get("H2GIS_LIB_PATH")
    if env:
        return env
    package_dir = os.path.dirname(os.path.abspath(__file__))
    name = library_file_name()
    bundled = os.path.join(package_dir, "lib", name)
    if os.path.exists(bundled):
        return bundled
    checkout = os.path.join(os.path.dirname(package_dir), "native", native_platform(), name)
    if os.path.exists(checkout):
        return checkout
    return bundled  # missing: NativeLib reports the expected location


class NativeLib:
    """A loaded native library and its GraalVM isolate.

    Don't instantiate directly: use :func:`get_lib`, which returns one shared
    instance per library path.
    """

    def __init__(self, path: str):
        if not os.path.exists(path):
            raise errors.InterfaceError(
                f"native H2GIS library not found: {path!r}. Install the h2gis "
                "package with its 'lib' folder, set H2GIS_LIB_PATH or pass lib_path=")
        self.path = path
        try:
            self._lib = ctypes.CDLL(path)
        except OSError as exc:
            raise errors.InterfaceError(f"cannot load native library {path!r}: {exc}") from exc

        if getattr(self._lib, "h2gis_version", None) is None:
            raise errors.InterfaceError(
                f"{path!r} implements the H2GIS C API version 1; h2gis-python 2 needs "
                f"version {MIN_C_API_VERSION} or later (H2GIS >= 2.2.6)")
        missing = [name for name in _FUNCTIONS if getattr(self._lib, name, None) is None]
        if missing:
            raise errors.InterfaceError(f"{path!r} has no entry point {', '.join(missing)}")
        for name, (args, res) in _FUNCTIONS.items():
            fn = getattr(self._lib, name)
            fn.argtypes, fn.restype = args, res

        self._lib.graal_create_isolate.argtypes = [
            _c_void_p, ctypes.POINTER(_Isolate_p), ctypes.POINTER(_Thread_p)]
        self._lib.graal_create_isolate.restype = ctypes.c_int
        self._lib.graal_attach_thread.argtypes = [_Isolate_p, ctypes.POINTER(_Thread_p)]
        self._lib.graal_attach_thread.restype = ctypes.c_int
        self._lib.graal_detach_thread.argtypes = [_Thread_p]
        self._lib.graal_detach_thread.restype = ctypes.c_int

        self._isolate = _Isolate_p()
        thread = _Thread_p()
        rc = self._lib.graal_create_isolate(None, ctypes.byref(self._isolate), ctypes.byref(thread))
        if rc != 0:
            raise errors.InterfaceError(f"failed to create the GraalVM isolate (code {rc})")
        self._local = threading.local()
        self._local.thread = thread

        self.version: int = self._lib.h2gis_version(thread)
        if self.version < MIN_C_API_VERSION:
            raise errors.InterfaceError(
                f"{path!r} implements the H2GIS C API version {self.version}; "
                f"h2gis-python 2 needs version {MIN_C_API_VERSION} or later")

    # -- isolate thread -------------------------------------------------------

    @property
    def thread(self):
        thread = getattr(self._local, "thread", None)
        if thread is None:
            thread = _Thread_p()
            rc = self._lib.graal_attach_thread(self._isolate, ctypes.byref(thread))
            if rc != 0:
                raise errors.InterfaceError(f"failed to attach thread to the isolate (code {rc})")
            self._local.thread = thread
            # Detach when the Python thread ends: CPython clears the thread
            # local storage from the exiting thread itself, which is what
            # graal_detach_thread requires. A thread that exits while still
            # attached crashes the isolate at its next safepoint.
            self._local.detacher = _Detacher(self._lib, thread)
        return thread

    # -- strings, errors ------------------------------------------------------

    def _take_string(self, ptr) -> str:
        """Read and free a string allocated by the library."""
        if not ptr:
            return ""
        try:
            return ctypes.string_at(ptr).decode("utf-8", "replace")
        finally:
            self._lib.h2gis_free_result_buffer(self.thread, ptr)

    def last_error(self) -> str:
        return self._take_string(self._lib.h2gis_get_last_error(self.thread))

    def _raise(self, what: str, default=errors.DatabaseError):
        message = self.last_error()
        if not message:
            raise default(f"{what} failed (no error message from the native library)")
        raise errors.from_native_message(message, default)

    # -- connections ----------------------------------------------------------

    def connect(self, path: str, user: str, password: str) -> int:
        handle = self._lib.h2gis_connect(self.thread, _encode(path), _encode(user), _encode(password))
        if not handle:
            self._raise("connection", errors.OperationalError)
        return handle

    def close_connection(self, conn: int) -> None:
        self._lib.h2gis_close_connection(self.thread, conn)

    def delete_database_and_close(self, conn: int) -> None:
        self._lib.h2gis_delete_database_and_close(self.thread, conn)
        message = self.last_error()
        if message:
            raise errors.from_native_message(message, errors.OperationalError)

    def load_functions(self, conn: int) -> None:
        """Register the H2GIS spatial functions (done by connect() when missing)."""
        if not self._lib.h2gis_load(self.thread, conn):
            self._raise("loading the H2GIS functions")

    # -- plain statements -----------------------------------------------------

    def execute(self, conn: int, sql: str) -> int:
        """Run an update statement (or a script), return the update count."""
        count = self._lib.h2gis_execute(self.thread, conn, _encode(sql))
        if count < 0:
            self._raise("execute")
        return count

    def query(self, conn: int, sql: str) -> int:
        """Run a query, return a result set handle."""
        handle = self._lib.h2gis_fetch(self.thread, conn, _encode(sql))
        if not handle:
            self._raise("query")
        return handle

    def close_query(self, handle: int) -> None:
        """Close a result set or statement handle (and the results of a statement)."""
        self._lib.h2gis_close_query(self.thread, handle)

    # -- prepared statements --------------------------------------------------

    def prepare(self, conn: int, sql: str) -> int:
        handle = self._lib.h2gis_prepare(self.thread, conn, _encode(sql))
        if not handle:
            self._raise("prepare", errors.ProgrammingError)
        return handle

    def bind(self, stmt: int, index: int, kind: str, value) -> None:
        """Bind one parameter (1-based ``index``) as returned by ``adapt.bind_value``."""
        lib, th = self._lib, self.thread
        if kind == "null":
            rc = lib.h2gis_bind_null(th, stmt, index)
        elif kind == "long":
            rc = lib.h2gis_bind_long(th, stmt, index, value)
        elif kind == "double":
            rc = lib.h2gis_bind_double(th, stmt, index, value)
        elif kind == "string":
            rc = lib.h2gis_bind_string(th, stmt, index, value.encode("utf-8"))
        elif kind == "blob":
            data = bytes(value)
            rc = lib.h2gis_bind_blob(th, stmt, index, data, len(data))
        else:  # pragma: no cover - guarded by adapt.bind_value
            raise errors.InterfaceError(f"unknown bind kind {kind!r}")
        if rc != 0:
            self._raise(f"binding parameter {index}", errors.DataError)

    def execute_prepared(self, stmt: int) -> int:
        handle = self._lib.h2gis_execute_prepared(self.thread, stmt)
        if not handle:
            self._raise("prepared query")
        return handle

    def execute_prepared_update(self, stmt: int) -> int:
        count = self._lib.h2gis_execute_prepared_update(self.thread, stmt)
        if count < 0:
            self._raise("prepared update")
        return count

    def add_batch(self, stmt: int) -> None:
        if self._lib.h2gis_add_batch(self.thread, stmt) != 0:
            self._raise("add batch")

    def execute_batch(self, stmt: int) -> int:
        count = self._lib.h2gis_execute_batch(self.thread, stmt)
        if count < 0:
            self._raise("execute batch")
        return count

    # -- results --------------------------------------------------------------

    def _buffer(self, fn, what: str, *args) -> bytes:
        size = ctypes.c_int64(0)
        ptr = fn(self.thread, *args, ctypes.byref(size))
        if not ptr:
            self._raise(what, errors.FetchError)
        try:
            return ctypes.string_at(ptr, size.value)
        finally:
            self._lib.h2gis_free_result_buffer(self.thread, ptr)

    def fetch_all(self, rs: int) -> bytes:
        """Serialized remaining rows (see _buffer.py)."""
        return self._buffer(self._lib.h2gis_fetch_all, "fetch", rs)

    def fetch_batch(self, rs: int, size: int) -> bytes:
        """Serialized next ``size`` rows; fewer rows means the end is reached."""
        return self._buffer(self._lib.h2gis_fetch_batch, "fetch", rs, int(size))

    def metadata(self, rs: int) -> List[dict]:
        """Column metadata: ``[{"name", "typeName", "type"}, ...]``."""
        raw = self._take_string(self._lib.h2gis_get_metadata_json(self.thread, rs))
        try:
            return json.loads(raw) if raw else []
        except ValueError:
            return []


class _Detacher:
    __slots__ = ("lib", "thread")

    def __init__(self, lib, thread):
        self.lib, self.thread = lib, thread

    def __del__(self):
        try:
            self.lib.graal_detach_thread(self.thread)
        except Exception:  # pragma: no cover - interpreter shutdown
            pass


def _encode(text: str) -> bytes:
    if not isinstance(text, str):
        raise errors.InterfaceError(f"expected str, got {type(text).__name__}")
    if "\x00" in text:
        raise errors.DataError("NUL characters are not allowed in SQL strings")
    return text.encode("utf-8")


_LIBS: Dict[str, NativeLib] = {}
_LIBS_LOCK = threading.Lock()


def get_lib(path: Optional[str] = None) -> NativeLib:
    """Return the shared :class:`NativeLib` for ``path`` (default library if None)."""
    path = os.path.realpath(path or default_library_path())
    with _LIBS_LOCK:
        lib = _LIBS.get(path)
        if lib is None:
            lib = _LIBS[path] = NativeLib(path)
        return lib
