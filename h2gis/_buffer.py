"""
H2GIS-python is a Python wrapper to use H2GIS <http://www.h2gis.org/>.
H2GIS-python is developed by CNRS <http://www.cnrs.fr/>.

This code is part of the H2GIS-python project. H2GIS-python is free software;
you can redistribute it and/or modify it under the terms of the GNU
Lesser General Public License as published by the Free Software Foundation;
version 3.0 of the License. See <http://www.gnu.org/licenses/>.

Decoder of the column oriented buffer produced by
``org.h2gis.graalvm.ResultSetWrapper.serialize()`` (all integers little endian)::

    u32 column_count
    u32 row_count
    u64 column_offset[column_count]        # from the start of the buffer
    column*:
        u32 name_length, utf-8 name
        u32 type_code                      # see adapt.ColumnType, | 0x100 if a null mask follows
        [u8 null_mask[ceil(row_count/8)]]  # bit i % 8 of byte i // 8 set: row i is NULL
        u32 values_length
        values:
            INT i32 | LONG i64 | FLOAT f32 | DOUBLE f64 | BOOLEAN u8
            other types: u32 length + bytes per value

NULL values keep a placeholder in ``values``; the mask tells them apart.
"""

from __future__ import annotations

import struct
from typing import List

from . import errors
from .adapt import ColumnType

NULL_LENGTH = 0xFFFFFFFF
FLAG_NULL_MASK = 0x100

_FIXED = {
    ColumnType.INT: "i",
    ColumnType.LONG: "q",
    ColumnType.FLOAT: "f",
    ColumnType.DOUBLE: "d",
}


class Chunk:
    """A decoded buffer: column names, type codes and values by column."""

    __slots__ = ("names", "type_codes", "row_count", "columns", "has_null_mask")

    def __init__(self, names, type_codes, row_count, columns, has_null_mask):
        self.names: List[str] = names
        self.type_codes: List[int] = type_codes
        self.row_count: int = row_count
        self.columns: List[list] = columns
        self.has_null_mask: List[bool] = has_null_mask


def decode(buf: bytes) -> Chunk:
    view = memoryview(buf)
    try:
        col_count, row_count = struct.unpack_from("<II", view, 0)
        offsets = struct.unpack_from(f"<{col_count}Q", view, 8)
        names, codes, columns, masks = [], [], [], []
        for offset in offsets:
            name_len = struct.unpack_from("<I", view, offset)[0]
            pos = offset + 4
            names.append(bytes(view[pos:pos + name_len]).decode("utf-8", "replace"))
            pos += name_len
            raw_code = struct.unpack_from("<I", view, pos)[0]
            pos += 4
            code = raw_code & ~FLAG_NULL_MASK
            nulls = None
            if raw_code & FLAG_NULL_MASK:
                mask_len = (row_count + 7) // 8
                nulls = bytes(view[pos:pos + mask_len])
                pos += mask_len
            values_len = struct.unpack_from("<I", view, pos)[0]
            pos += 4
            values = _decode_values(view[pos:pos + values_len], code, row_count)
            if nulls is not None:
                for i in range(row_count):
                    if nulls[i >> 3] & (1 << (i & 7)):
                        values[i] = None
            codes.append(code)
            columns.append(values)
            masks.append(nulls is not None)
    except (struct.error, IndexError, UnicodeDecodeError) as exc:
        raise errors.InterfaceError(f"malformed result buffer: {exc}") from exc
    return Chunk(names, codes, row_count, columns, masks)


def _decode_values(view: memoryview, code: int, n: int) -> list:
    fmt = _FIXED.get(code)
    if fmt is not None:
        return list(struct.unpack_from(f"<{n}{fmt}", view, 0)) if n else []
    if code == ColumnType.BOOLEAN:
        return [b != 0 for b in bytes(view[:n])]
    out: list = []
    pos = 0
    as_text = code not in (ColumnType.GEOMETRY, ColumnType.BINARY)
    for _ in range(n):
        length = struct.unpack_from("<I", view, pos)[0]
        pos += 4
        if length == NULL_LENGTH:
            out.append(None)
            continue
        data = bytes(view[pos:pos + length])
        if len(data) != length:
            raise errors.InterfaceError("malformed result buffer: truncated value")
        pos += length
        out.append(data.decode("utf-8", "replace") if as_text else data)
    return out
