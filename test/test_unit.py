"""
Unit tests of the pure Python parts (no native library needed).
"""

import datetime as dt
import decimal
import struct
import re
import uuid

import pytest
import shapely

import h2gis
from h2gis import errors, rows, sql
from h2gis._buffer import FLAG_NULL_MASK, NULL_LENGTH, decode
from h2gis._queries import first_keyword, has_side_effects, is_query, render_binds, render_literals, split_query
from h2gis.adapt import AdaptersMap, ColumnType, Geometry, adapters
from h2gis.connection import _normalize_path


# --- buffer -----------------------------------------------------------------

def encode(columns, row_count, null_masks=None):
    """Python mirror of ResultSetWrapper.serialize() (+ optional null masks)."""
    blobs = []
    for idx, (name, code, values) in enumerate(columns):
        out = bytearray()
        nb = name.encode()
        out += struct.pack("<I", len(nb)) + nb
        mask = null_masks[idx] if null_masks else None
        out += struct.pack("<I", code | (FLAG_NULL_MASK if mask is not None else 0))
        if mask is not None:
            m = bytearray((row_count + 7) // 8)
            for i, isnull in enumerate(mask):
                if isnull:
                    m[i >> 3] |= 1 << (i & 7)
            out += m
        data = bytearray()
        for v in values:
            if code == 1:
                data += struct.pack("<i", v)
            elif code == 2:
                data += struct.pack("<q", v)
            elif code == 3:
                data += struct.pack("<f", v)
            elif code == 4:
                data += struct.pack("<d", v)
            elif code == 5:
                data += bytes([1 if v else 0])
            elif v is None:
                data += struct.pack("<I", NULL_LENGTH)
            else:
                b = v if isinstance(v, bytes) else v.encode()
                data += struct.pack("<I", len(b)) + b
        out += struct.pack("<I", len(data)) + data
        blobs.append(bytes(out))
    header = struct.pack("<II", len(columns), row_count)
    offset = 8 + 8 * len(columns)
    for b in blobs:
        header += struct.pack("<Q", offset)
        offset += len(b)
    return header + b"".join(blobs)


def test_decode_all_types():
    wkb = shapely.to_wkb(shapely.Point(1, 2))
    buf = encode([("I", 1, [1, -2]), ("L", 2, [2 ** 40, 0]), ("F", 3, [1.5, 0]),
                  ("D", 4, [2.25, -1]), ("B", 5, [True, False]), ("S", 6, ["é", None]),
                  ("G", 8, [wkb, None]), ("BIN", 9, [b"\x00\xff", b""]),
                  ("N", 10, ["1.10", "2"]), ("J", 11, ['{"a":1}', "[]"]),
                  ("U", 12, ["123e4567-e89b-12d3-a456-426614174000", None])], 2)
    chunk = decode(buf)
    assert chunk.names == ["I", "L", "F", "D", "B", "S", "G", "BIN", "N", "J", "U"]
    assert chunk.type_codes == [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12]
    assert chunk.columns[:7] == [[1, -2], [2 ** 40, 0], [1.5, 0.0], [2.25, -1.0], [True, False],
                                 ["é", None], [wkb, None]]
    assert chunk.columns[7] == [b"\x00\xff", b""]  # binary stays bytes
    assert chunk.columns[8] == ["1.10", "2"]


def test_decode_null_mask():
    buf = encode([("I", 1, [1, 0, 3]), ("S", 6, ["a", "", "c"])], 3,
                 null_masks=[[False, True, False], [False, True, False]])
    chunk = decode(buf)
    assert chunk.columns == [[1, None, 3], ["a", None, "c"]]
    assert chunk.has_null_mask == [True, True]


def test_decode_empty_and_malformed():
    chunk = decode(encode([("A", 1, [])], 0))
    assert chunk.row_count == 0 and chunk.columns == [[]]
    with pytest.raises(errors.InterfaceError):
        decode(b"\x01\x00\x00\x00\x05\x00")


# --- errors -----------------------------------------------------------------

def test_error_mapping_english():
    msg = ('Failed to execute query: Table "NOPE" not found; SQL statement:\n'
           'SELECT * FROM NOPE [42102-232]')
    exc = errors.from_native_message(msg)
    assert isinstance(exc, errors.UndefinedTable)
    assert isinstance(exc, errors.ProgrammingError)
    assert exc.h2_code == 42102 and exc.sqlstate == "42S02"
    assert str(exc).startswith('Table "NOPE" not found')


def test_error_mapping_localized():
    msg = ("Failed to execute update: Violation d'index unique ou clé primaire: \"PK\"\n"
           'Unique index or primary key violation: "PK"; SQL statement:\n'
           "INSERT INTO U VALUES (1) [23505-232]")
    exc = errors.from_native_message(msg)
    assert isinstance(exc, errors.UniqueViolation) and isinstance(exc, errors.IntegrityError)
    assert str(exc).startswith("Unique index or primary key violation")
    assert exc.sqlstate == "23505"


@pytest.mark.parametrize("code,cls", [
    (22018, errors.InvalidTextRepresentation), (90020, errors.DatabaseAlreadyOpen),
    (42999, errors.ProgrammingError), (23999, errors.IntegrityError),
    (50200, errors.LockNotAvailable), (99999, errors.DatabaseError)])
def test_error_lookup(code, cls):
    assert errors.lookup(code) is cls


def test_error_without_code():
    exc = errors.from_native_message("Null pointer received", errors.OperationalError)
    assert type(exc) is errors.OperationalError and exc.h2_code is None


# --- placeholders -----------------------------------------------------------

def test_render_literals_positional():
    q = render_literals("SELECT %s, %s, %s, 'a%%b'", ["it's", None, True], adapters)
    assert q == "SELECT 'it''s', NULL, TRUE, 'a%b'"


def test_render_literals_named_repeated():
    q = render_literals("SELECT %(x)s + %(x)s, %(y)t", {"x": 1, "y": 2}, adapters)
    assert q == "SELECT 1 + 1, 2"


def test_no_params_verbatim():
    assert render_literals("SELECT '100%'", None, adapters) == "SELECT '100%'"


@pytest.mark.parametrize("query,params,msg", [
    ("SELECT %d", [1], "only '%s'"),
    ("SELECT %s, %(a)s", [1], "mixed"),
    ("SELECT %s", [1, 2], "1 placeholders but 2"),
    ("SELECT %(a)s", [1], "named placeholders"),
    ("SELECT %s", {"a": 1}, "mapping"),
    ("SELECT %(a)s", {"b": 1}, "missing"),
    ("SELECT %", [], "incomplete"),
    ("SELECT %s", "a", "sequence or a mapping"),
])
def test_placeholder_errors(query, params, msg):
    with pytest.raises(errors.ProgrammingError, match=msg):
        render_literals(query, params, adapters)


def test_render_binds_casts():
    g = shapely.set_srid(shapely.Point(1, 2), 4326)
    q, binds = render_binds("INSERT INTO t VALUES (%s, %s, %s, %s, %s, %s)",
                            [1, "x", None, g, dt.date(2024, 1, 2), [1, 2]], adapters)
    assert q == ("INSERT INTO t VALUES (?, ?, ?, CAST(? AS GEOMETRY), CAST(? AS DATE), "
                 "ARRAY[1, 2])")
    assert [k for k, _ in binds] == ["long", "string", "null", "blob", "string"]
    assert shapely.get_srid(shapely.from_wkb(binds[3][1])) == 4326


def test_split_query():
    parts = split_query("a %s b %% c")
    assert parts[0] == "a " and parts[-1] == " c"


# --- literals and injection ----------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, "NULL"), (False, "FALSE"), (42, "42"), (2 ** 70, f"CAST({2 ** 70} AS NUMERIC)"),
    (1.5, "CAST(1.5 AS DOUBLE PRECISION)"), (float("nan"), "CAST('NaN' AS DOUBLE PRECISION)"),
    (float("-inf"), "CAST('-Infinity' AS DOUBLE PRECISION)"),
    (decimal.Decimal("1.10"), "CAST('1.10' AS DECFLOAT)"),
    (decimal.Decimal("NaN"), "CAST('NaN' AS DECFLOAT)"),
    ("'; DROP TABLE t; --", "'''; DROP TABLE t; --'"), (b"\x01\xff", "X'01ff'"),
    (dt.date(2024, 1, 2), "DATE '2024-01-02'"),
    (dt.datetime(2024, 1, 2, 3, 4, 5), "TIMESTAMP '2024-01-02 03:04:05'"),
    (dt.datetime(2024, 1, 2, tzinfo=dt.timezone.utc), "TIMESTAMP WITH TIME ZONE '2024-01-02 00:00:00+00:00'"),
    (dt.time(1, 2, 3), "TIME '01:02:03'"),
    (uuid.UUID(int=1), "CAST('00000000-0000-0000-0000-000000000001' AS UUID)"),
    (h2gis.Json({"a": "it's"}), """'{"a": "it''s"}' FORMAT JSON"""),
    ([1, "a"], "ARRAY[1, 'a']"),
])
def test_literals(value, expected):
    assert adapters.literal(value) == expected


def test_literal_geometry_and_errors():
    lit = adapters.literal(Geometry(shapely.Point(1, 2), srid=2154))
    assert lit.startswith("CAST(X'") and lit.endswith("' AS GEOMETRY)")
    ewkb = bytes.fromhex(lit[len("CAST(X'"):-len("' AS GEOMETRY)")])
    assert shapely.get_srid(shapely.from_wkb(ewkb)) == 2154
    with pytest.raises(errors.DataError):
        adapters.literal("a\x00b")
    with pytest.raises(errors.ProgrammingError, match="cannot adapt"):
        adapters.literal(object())


def test_custom_dumper_and_loader():
    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y
    amap = AdaptersMap(adapters)
    amap.register_dumper(P, lambda p: shapely.Point(p.x, p.y))
    assert amap.bind_value(P(1, 2))[0] == "blob"
    assert "P" not in [c.__name__ for c in adapters._dumpers]  # global map untouched
    amap.register_loader("CHARACTER VARYING", str.upper)
    assert amap.loader(ColumnType.STRING, "CHARACTER VARYING")("abc") == "ABC"


# --- loaders ----------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("2024-01-02", dt.date(2024, 1, 2)),
    ("2024-01-02 10:11:12.5", dt.datetime(2024, 1, 2, 10, 11, 12, 500000)),
    ("2024-01-02 10:11:12.123456789", dt.datetime(2024, 1, 2, 10, 11, 12, 123456)),
    ("10:11:12", dt.time(10, 11, 12)),
    ("2024-01-02T10:11:12+02:00",
     dt.datetime(2024, 1, 2, 10, 11, 12, tzinfo=dt.timezone(dt.timedelta(hours=2)))),
    ("2024-01-02T10:11", dt.datetime(2024, 1, 2, 10, 11)),   # java.time ISO without seconds
    ("10:11", dt.time(10, 11)),
    ("10:11:12.5+01:00", dt.time(10, 11, 12, 500000, tzinfo=dt.timezone(dt.timedelta(hours=1)))),
    ("0000-01-01", "0000-01-01"),                              # out of Python's range
])
def test_temporal_loader(text, expected):
    assert adapters.loader(ColumnType.DATE, None)(text) == expected


def test_type_loaders():
    assert adapters.loader(ColumnType.DECIMAL, "NUMERIC")("12345678901234.1234567891") == \
        decimal.Decimal("12345678901234.1234567891")
    assert adapters.loader(ColumnType.DECIMAL, "DECFLOAT")("NaN").is_nan()
    assert adapters.loader(ColumnType.JSON, "JSON")('{"a": [1, 2]}') == {"a": [1, 2]}
    u = adapters.loader(ColumnType.UUID, "UUID")("123e4567-e89b-12d3-a456-426614174000")
    assert isinstance(u, uuid.UUID)
    assert adapters.loader(ColumnType.BINARY, None)(b"\x01") == b"\x01"
    assert adapters.loader(ColumnType.OTHER, None)("[1, 2]") == "[1, 2]"


def test_json_bind():
    q, binds = render_binds("INSERT INTO t VALUES (%s)", [h2gis.Json([1, {"b": None}])], adapters)
    assert q == "INSERT INTO t VALUES (? FORMAT JSON)"
    assert binds == [("string", '[1, {"b": null}]')]


def test_geometry_loader_keeps_srid():
    ewkb = shapely.to_wkb(shapely.set_srid(shapely.Point(1, 2), 4326), include_srid=True)
    g = adapters.loader(ColumnType.GEOMETRY, None)(ewkb)
    assert shapely.get_srid(g) == 4326


# --- statement classification ----------------------------------------------------

@pytest.mark.parametrize("q,expected", [
    ("SELECT 1", True), ("  -- c\n /* x */ ( select 1)", True), ("WITH a AS (SELECT 1) SELECT *", True),
    ("CALL 1+1", True), ("INSERT INTO t VALUES (1)", False), ("CREATE TABLE t(a int)", False),
    ("", None),
])
def test_is_query(q, expected):
    assert is_query(q) is expected


def test_side_effects():
    assert has_side_effects("SELECT * FROM FINAL TABLE (INSERT INTO t VALUES (1))")
    assert has_side_effects("CALL GeoJsonRead('x.geojson')")
    assert not has_side_effects("SELECT * FROM t")
    assert first_keyword("/*a*/select") == "SELECT"


# --- sql composition ----------------------------------------------------------

def test_sql_compose():
    q = sql.SQL("SELECT {cols} FROM {t} WHERE {c} = {v} AND x = {p}").format(
        cols=sql.SQL(", ").join([sql.Identifier("A"), sql.Identifier('we"ird')]),
        t=sql.Identifier("PUBLIC", "T"), c=sql.Identifier("A"), v=sql.Literal("o'k"),
        p=sql.Placeholder("x"))
    assert q.as_string() == ('SELECT "A", "we""ird" FROM "PUBLIC"."T" WHERE "A" = \'o\'\'k\' '
                             'AND x = %(x)s')


def test_sql_format_errors():
    with pytest.raises(TypeError):
        sql.SQL("{}").format("raw string")
    with pytest.raises(ValueError):
        sql.SQL("{} {0}").format(sql.NULL, sql.NULL)
    with pytest.raises(ValueError):
        sql.SQL("{:>10}").format(sql.NULL)
    assert (sql.SQL("a") + sql.SQL("b")).as_string() == "ab"
    assert sql.quote("x'y") == "'x''y'"


# --- rows ---------------------------------------------------------------------

class _FakeCursor:
    description = [h2gis.Column("ID", 1), h2gis.Column("my col", 6), h2gis.Column("2", 1)]


def test_row_factories():
    cur = _FakeCursor()
    values = (1, "a", 2)
    assert rows.tuple_row(cur)(values) == values
    assert rows.dict_row(cur)(values) == {"ID": 1, "my col": "a", "2": 2}
    nt = rows.namedtuple_row(cur)(values)
    assert nt.ID == 1 and nt.my_col == "a" and nt[2] == 2
    assert rows.args_row(lambda *a: sum(a[::2]))(cur)(values) == 3
    assert rows.kwargs_row(lambda **k: k["ID"])(cur)(values) == 1


def test_column_is_pep249_sequence():
    col = h2gis.Column("G", 8, "GEOMETRY")
    assert len(col) == 7 and col[0] == "G" and col.type_name == "GEOMETRY"
    assert col.type_code == h2gis.GEOMETRY and h2gis.Column("N", 4).type_code == h2gis.NUMBER
    assert h2gis.Column("B", 9).type_code == h2gis.BINARY and h2gis.Column("D", 10).type_code == h2gis.NUMBER
    assert h2gis.Column("X", 99).type_name == "OTHER"


# --- module ----------------------------------------------------------------------

def test_module_globals():
    assert h2gis.apilevel == "2.0" and h2gis.paramstyle == "pyformat"
    assert h2gis.threadsafety in (1, 2)
    assert issubclass(h2gis.errors.UndefinedTable, h2gis.DatabaseError)
    assert h2gis.Date(2024, 1, 2) == dt.date(2024, 1, 2)
    assert isinstance(h2gis.TimestampFromTicks(0), dt.datetime)


@pytest.mark.parametrize("path,expected", [
    ("data/db", "./data/db"), ("db.mv.db", "./db"), ("/abs/db;AUTO_SERVER=TRUE", "/abs/db;AUTO_SERVER=TRUE"),
    ("mem:test", "mem:test"), ("./x", "./x"), ("~/x", "~/x"), ("C:\\data\\db", "C:\\data\\db"),
    ("tcp://localhost/~/db", "tcp://localhost/~/db"),
])
def test_normalize_path(path, expected):
    assert _normalize_path(path) == expected


def test_library_lookup(tmp_path, monkeypatch):
    from h2gis import _native
    assert re.match(r"^(linux|windows|macos)-[a-z0-9_]+$", _native.native_platform())
    assert _native.library_file_name() in ("h2gis.so", "h2gis.dll", "h2gis.dylib")
    monkeypatch.setenv("H2GIS_LIB_PATH", "/explicit/h2gis.so")
    assert _native.default_library_path() == "/explicit/h2gis.so"
    monkeypatch.delenv("H2GIS_LIB_PATH")
    # a fake checkout: package without lib/, library in native/<platform>/
    pkg = tmp_path / "h2gis"
    pkg.mkdir()
    lib = tmp_path / "native" / _native.native_platform() / _native.library_file_name()
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b"")
    monkeypatch.setattr(_native, "__file__", str(pkg / "_native.py"))
    assert _native.default_library_path() == str(lib)
    (pkg / "lib").mkdir()
    bundled = pkg / "lib" / _native.library_file_name()
    bundled.write_bytes(b"")
    assert _native.default_library_path() == str(bundled)  # the wheel's library wins
