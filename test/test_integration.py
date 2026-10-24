"""
Integration tests against real native libraries (see conftest.py).
"""

import datetime as dt
import decimal
import os
import subprocess
import sys
import threading
import uuid
import warnings

import pytest
import shapely

import h2gis
from h2gis import errors, sql
from h2gis.rows import class_row, dict_row, namedtuple_row

WGS84_POINT = shapely.set_srid(shapely.Point(2.35, 48.85), 4326)


@pytest.fixture
def places(conn):
    conn.execute("CREATE TABLE PLACE_NAMES(ID INT PRIMARY KEY, NOM VARCHAR, D TIMESTAMP, "
                 "THE_GEOM GEOMETRY(POINT, 4326))")
    conn.cursor().executemany(
        "INSERT INTO PLACE_NAMES VALUES (%s, %s, %s, %s)",
        [(1, "Paris", dt.datetime(2024, 5, 1, 12, 30), WGS84_POINT),
         (2, "Lyon", None, shapely.set_srid(shapely.Point(4.83, 45.76), 4326)),
         (3, "No name", dt.datetime(2020, 1, 1), None)])
    conn.commit()
    return conn


@pytest.fixture(params=[None, False], ids=["auto", "literals"])
def mode(request):
    return request.param


# --- basics -----------------------------------------------------------------

def test_types_roundtrip(conn, mode):
    cur = conn.execute(
        "SELECT %s AS I, %s AS L, %s AS F, %s AS B, %s AS S, %s AS D, %s AS TS, %s AS TM, "
        "%s AS G, %s AS N",
        [42, 2 ** 40, 1.25, True, "l'été", dt.date(2024, 1, 2),
         dt.datetime(2024, 1, 2, 3, 4, 5, 600000), dt.time(10, 11, 12), WGS84_POINT, None],
        prepare=mode)
    row = cur.fetchone()
    assert row[:8] == (42, 2 ** 40, 1.25, True, "l'été", dt.date(2024, 1, 2),
                       dt.datetime(2024, 1, 2, 3, 4, 5, 600000), dt.time(10, 11, 12))
    assert row[8].equals(WGS84_POINT) and shapely.get_srid(row[8]) == 4326
    assert [c.name for c in cur.description] == ["I", "L", "F", "B", "S", "D", "TS", "TM", "G", "N"]
    assert cur.description[8].type_code == h2gis.GEOMETRY
    assert cur.fetchone() is None
    assert cur.rowcount == 1


def test_injection_is_harmless(conn, mode):
    conn.execute("CREATE TABLE T(S VARCHAR)")
    evil = "x'); DROP TABLE T; --"
    conn.execute("INSERT INTO T VALUES (%s)", [evil], prepare=mode)
    assert conn.execute("SELECT S FROM T").fetchall() == [(evil,)]


def test_execute_returns_cursor_and_iteration(places):
    names = [r[0] for r in places.execute("SELECT NOM FROM PLACE_NAMES ORDER BY ID")]
    assert names == ["Paris", "Lyon", "No name"]
    cur = places.execute("SELECT ID FROM PLACE_NAMES ORDER BY ID")
    assert cur.fetchmany(2) == [(1,), (2,)] and cur.rownumber == 2
    assert cur.fetchall() == [(3,)] and cur.fetchall() == []


def test_update_rowcount_and_description(places):
    cur = places.execute("UPDATE PLACE_NAMES SET NOM = UPPER(NOM) WHERE ID > %s", [1])
    assert cur.rowcount == 2 and cur.description is None
    with pytest.raises(errors.ProgrammingError):
        cur.fetchone()


def test_select_through_execute_fallback(conn):
    # first keyword unknown to the classifier: the native error code decides
    assert conn.execute("SHOW TABLES").description is not None
    assert conn.execute("CALL 1 + 1").fetchone() == (2,)


@pytest.mark.parametrize("guess", [False, None])
def test_misclassified_query(conn, mode, guess, monkeypatch):
    # a query classified as an update is retried as a query (H2 error 90001)
    monkeypatch.setattr("h2gis.cursor.is_query", lambda q: guess)
    cur = conn.execute("SELECT %s AS X", [5], prepare=mode)
    assert cur.description[0].name == "X" and cur.fetchone() == (5,)
    assert conn.execute("SELECT 6").fetchone() == (6,)
    monkeypatch.setattr("h2gis.cursor.is_query", lambda q: True)
    conn.execute("CREATE TABLE T(A INT)")
    assert conn.execute("INSERT INTO T VALUES (%s)", [1], prepare=mode).rowcount == 1


def test_script_without_params(conn):
    conn.execute("CREATE TABLE M(A INT); INSERT INTO M VALUES (1); INSERT INTO M VALUES (2)")
    assert conn.execute("SELECT COUNT(*) FROM M").fetchone() == (2,)


def test_percent_without_params(conn):
    assert conn.execute("SELECT '100%'").fetchone() == ("100%",)
    assert conn.execute("SELECT '100%%', %s", [1]).fetchone() == ("100%", 1)


def test_duplicate_column_names(conn):
    cur = conn.execute("SELECT 1 AS A, 2 AS A")
    assert cur.fetchone() == (1, 2)  # tuples keep both columns
    with pytest.raises(errors.ProgrammingError, match="duplicate"):
        conn.execute("SELECT 1 AS A, 2 AS A").fetch_columns()


# --- NULL handling -------------------------------------------------------------

def test_null_geometry(places):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        rows = places.execute("SELECT ID, THE_GEOM FROM PLACE_NAMES ORDER BY ID").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3]
    assert rows[2][1] is None and rows[0][1].equals(WGS84_POINT)


def test_null_geometry_with_params(places, mode):
    rows = places.execute("SELECT ID, THE_GEOM FROM PLACE_NAMES WHERE ID >= %s ORDER BY ID",
                          [2], prepare=mode).fetchall()
    assert [r[0] for r in rows] == [2, 3] and rows[1][1] is None


def test_null_geometry_in_stream(places):
    places.execute("INSERT INTO PLACE_NAMES SELECT X, 'n', NULL, CASE WHEN MOD(X, 7) = 0 THEN NULL "
                   "ELSE ST_SetSRID(ST_MakePoint(X, X), 4326) END FROM SYSTEM_RANGE(10, 509)")
    cur = places.cursor()
    ids, nulls = [], 0
    for row in cur.stream("SELECT ID, THE_GEOM FROM PLACE_NAMES ORDER BY ID", size=64):
        ids.append(row[0])
        nulls += row[1] is None
    assert ids == [1, 2, 3] + list(range(10, 510))
    assert nulls == 1 + sum(1 for x in range(10, 510) if x % 7 == 0)
    assert cur.rowcount == len(ids)


def test_null_dates(places):
    assert places.execute("SELECT D FROM PLACE_NAMES WHERE ID = 2").fetchone() == (None,)


def test_nulls_of_every_type(conn):
    conn.execute("CREATE TABLE N(I INT, L BIGINT, R REAL, D DOUBLE PRECISION, B BOOLEAN, "
                 "S VARCHAR, T TIMESTAMP, G GEOMETRY, BIN VARBINARY, DEC NUMERIC(10, 2), "
                 "J JSON, U UUID)")
    conn.execute("INSERT INTO N VALUES (NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, "
                 "NULL, NULL, NULL)")
    conn.execute("INSERT INTO N(I, L, R, D, B, S, BIN) VALUES (0, 0, 0, 0, FALSE, '', X'')")
    rows = conn.execute("SELECT * FROM N").fetchall()
    assert rows[0] == (None,) * 12
    assert conn.execute("SELECT I, L, R, D, B, S, BIN FROM N WHERE I = 0").fetchone() == \
        (0, 0, 0.0, 0.0, False, "", b"")


def test_binary_decimal_json_uuid(conn, mode):
    conn.execute("CREATE TABLE X(BIN VARBINARY, DEC NUMERIC(30, 10), J JSON, U UUID, "
                 "DF DECFLOAT, TZ TIMESTAMP WITH TIME ZONE, TM TIME(6))")
    u = uuid.uuid4()
    tz = dt.datetime(2024, 1, 2, 10, 11, 12, 123456, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    conn.execute("INSERT INTO X VALUES (%s, %s, %s, %s, %s, %s, %s)",
                 [b"\x00\xff\x10", decimal.Decimal("12345678901234.1234567891"),
                  h2gis.Json({"a": [1, 2], "b": "l'été"}), u, decimal.Decimal("-1.5E+400"), tz,
                  dt.time(10, 11)], prepare=mode)
    row = conn.execute("SELECT * FROM X").fetchone()
    assert row[0] == b"\x00\xff\x10"
    assert row[1] == decimal.Decimal("12345678901234.1234567891")
    assert row[2] == {"a": [1, 2], "b": "l'été"}
    assert row[3] == u
    assert row[4] == decimal.Decimal("-1.5E+400")
    assert conn.execute("SELECT %s", [decimal.Decimal("0.1000000000000000000001")],
                        prepare=mode).fetchone() == (decimal.Decimal("0.1000000000000000000001"),)
    assert row[5] == tz and row[6] == dt.time(10, 11)
    desc = conn.execute("SELECT * FROM X").description
    assert [d.type_code for d in desc] == [9, 10, 11, 12, 10, 7, 7]
    assert desc[0].type_code == h2gis.BINARY and desc[3].type_name == "UUID"


def test_executemany_batches(conn, mode, monkeypatch):
    monkeypatch.setattr("h2gis.cursor.EXECUTEMANY_BATCH", 7)
    conn.execute("CREATE TABLE B(ID INT PRIMARY KEY, D DATE, S VARCHAR)")
    rows = [(i, dt.date(2024, 1, 1 + i % 28) if i % 3 else None, f"s{i}") for i in range(50)]
    cur = conn.cursor()
    cur.executemany("INSERT INTO B VALUES (%s, %s, %s)", rows, prepare=mode)
    assert cur.rowcount == 50
    assert conn.execute("SELECT * FROM B ORDER BY ID").fetchall() == rows
    with pytest.raises(errors.UniqueViolation):
        cur.executemany("INSERT INTO B VALUES (%s, %s, %s)", [(100, None, "x"), (1, None, "dup")],
                        prepare=mode)


def test_old_library_is_refused():
    old = os.environ.get("H2GIS_V1_LIB")
    if not old or not os.path.exists(old):
        pytest.skip("set H2GIS_V1_LIB to a C API v1 library (h2gis 0.0.3)")
    # separate process: two GraalVM libraries can't share one process
    code = ("import h2gis, sys\n"
            "try:\n    h2gis.connect('mem:x', lib_path=sys.argv[1])\n"
            "except h2gis.InterfaceError as e:\n    print('REFUSED', e)\n")
    out = subprocess.run([sys.executable, "-c", code, old], capture_output=True, text=True,
                         cwd=os.path.dirname(os.path.dirname(__file__)), timeout=120)
    assert "REFUSED" in out.stdout and "version 1" in out.stdout


# --- errors -----------------------------------------------------------------

def test_errors(conn):
    with pytest.raises(errors.UndefinedTable) as info:
        conn.execute("SELECT * FROM NOPE")
    assert info.value.sqlstate == "42S02" and "NOPE" in str(info.value)
    conn.execute("CREATE TABLE U(ID INT PRIMARY KEY)")
    conn.execute("INSERT INTO U VALUES (1)")
    with pytest.raises(errors.UniqueViolation):
        conn.execute("INSERT INTO U VALUES (%s)", [1])
    with pytest.raises(errors.DuplicateTable):
        conn.execute("CREATE TABLE U(X INT)")
    with pytest.raises(errors.InvalidTextRepresentation):
        conn.execute("INSERT INTO U VALUES ('abc')")
    with pytest.raises(errors.SyntaxError):
        conn.execute("SELEC 1")


def test_database_in_use(lib_path, tmp_path, conn):
    other = h2gis.connect(tmp_path / "db", lib_path=lib_path)  # same process: allowed by H2
    other.close()


@pytest.mark.parametrize("path", ["mem:spatial", "mem:"])
def test_spatial_functions_in_memory(lib_path, path):
    with h2gis.connect(path, lib_path=lib_path) as conn:
        assert conn.execute("SELECT ST_AsText(ST_MakePoint(1, 2))").fetchone() == ("POINT (1 2)",)


def test_closed(conn):
    cur = conn.cursor()
    conn.close()
    assert conn.closed
    with pytest.raises(errors.InterfaceError):
        conn.execute("SELECT 1")
    with pytest.raises(errors.InterfaceError):
        cur.execute("SELECT 1")
    conn.close()  # idempotent


# --- transactions ---------------------------------------------------------------

def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM U").fetchone()[0]


@pytest.fixture
def utable(conn):
    conn.execute("CREATE TABLE U(ID INT PRIMARY KEY)")
    conn.commit()
    return conn


def test_commit_rollback(utable):
    conn = utable
    conn.execute("INSERT INTO U VALUES (1)")
    conn.rollback()
    assert _count(conn) == 0
    conn.execute("INSERT INTO U VALUES (1)")
    conn.commit()
    conn.rollback()
    assert _count(conn) == 1


def test_connection_context_manager(lib_path, tmp_path):
    path = tmp_path / "ctx"
    with h2gis.connect(path, lib_path=lib_path) as conn:
        conn.execute("CREATE TABLE U(ID INT)")
        conn.execute("INSERT INTO U VALUES (1)")
    assert conn.closed
    with pytest.raises(RuntimeError):
        with h2gis.connect(path, lib_path=lib_path) as conn:
            conn.execute("INSERT INTO U VALUES (2)")
            raise RuntimeError
    with h2gis.connect(path, lib_path=lib_path) as conn:
        assert conn.execute("SELECT ID FROM U").fetchall() == [(1,)]


def test_nested_transactions(utable):
    conn = utable
    with conn.transaction():
        conn.execute("INSERT INTO U VALUES (1)")
        with conn.transaction():
            conn.execute("INSERT INTO U VALUES (2)")
            raise h2gis.Rollback  # only the inner block
        with pytest.raises(ValueError):
            with conn.transaction():
                conn.execute("INSERT INTO U VALUES (3)")
                raise ValueError
        with conn.transaction(force_rollback=True):
            conn.execute("INSERT INTO U VALUES (4)")
        with pytest.raises(errors.ProgrammingError):
            conn.commit()
    conn.rollback()  # the outer block already committed
    assert [r[0] for r in conn.execute("SELECT ID FROM U ORDER BY ID")] == [1]


def test_rollback_to_outer(utable):
    conn = utable
    with conn.transaction() as outer:
        conn.execute("INSERT INTO U VALUES (1)")
        with conn.transaction():
            conn.execute("INSERT INTO U VALUES (2)")
            raise h2gis.Rollback(outer)
    assert _count(conn) == 0


def test_failed_rollback_is_reported(utable):
    conn = utable
    with pytest.raises(errors.OperationalError, match="DDL"):
        with conn.transaction():
            conn.execute("INSERT INTO U VALUES (1)")
            with conn.transaction():
                conn.execute("CREATE TABLE B(X INT)")  # commits, kills the savepoint
                raise h2gis.Rollback


def test_autocommit(utable):
    conn = utable
    conn.autocommit = True
    conn.execute("INSERT INTO U VALUES (1)")
    with conn.transaction():
        conn.execute("INSERT INTO U VALUES (2)")
        raise h2gis.Rollback
    assert conn.autocommit
    conn.autocommit = False
    conn.execute("INSERT INTO U VALUES (3)")
    with pytest.raises(errors.ProgrammingError, match="autocommit"):
        conn.autocommit = True
    conn.rollback()
    assert [r[0] for r in conn.execute("SELECT ID FROM U")] == [1]


# --- row factories, sql ------------------------------------------------------------

def test_row_factories(places):
    assert places.execute("SELECT ID, NOM FROM PLACE_NAMES WHERE ID = 1").fetchone() == (1, "Paris")
    cur = places.cursor(row_factory=dict_row)
    assert cur.execute("SELECT ID, NOM FROM PLACE_NAMES WHERE ID = 1").fetchone() == {"ID": 1, "NOM": "Paris"}
    cur.row_factory = namedtuple_row
    assert cur.execute("SELECT ID, NOM FROM PLACE_NAMES WHERE ID = 1").fetchone().NOM == "Paris"

    class Place:
        def __init__(self, ID, NOM):
            self.id, self.nom = ID, NOM
    p = places.cursor(row_factory=class_row(Place)).execute(
        "SELECT ID, NOM FROM PLACE_NAMES WHERE ID = 2").fetchone()
    assert p.nom == "Lyon"


def test_sql_identifiers(places):
    q = sql.SQL("SELECT {} FROM {} WHERE {} = %s").format(
        sql.Identifier("NOM"), sql.Identifier("PUBLIC", "PLACE_NAMES"), sql.Identifier("ID"))
    assert places.execute(q, [2]).fetchone() == ("Lyon",)
    with pytest.raises(errors.UndefinedTable):  # quoted lower case is another table
        places.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier("place_names")))


def test_spatial_query_with_geometry_param(places, mode):
    zone = shapely.set_srid(shapely.box(2, 48, 3, 49), 4326)
    rows = places.execute("SELECT NOM FROM PLACE_NAMES WHERE ST_Intersects(THE_GEOM, %s)", [zone],
                          prepare=mode).fetchall()
    assert rows == [("Paris",)]


# --- threads ---------------------------------------------------------------------

def test_threads_share_connection(places):
    results, failures = [], []

    def work(i):
        try:
            results.append(places.execute("SELECT COUNT(*) + %s FROM PLACE_NAMES", [i]).fetchone()[0])
        except Exception as exc:  # pragma: no cover
            failures.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not failures and sorted(results) == [3 + i for i in range(8)]


# --- pandas / GeoPandas -------------------------------------------------------------

def test_read_gdf(places):
    gdf = h2gis.read_gdf(places, "SELECT * FROM PLACE_NAMES ORDER BY ID")
    assert list(gdf.columns) == ["ID", "NOM", "D", "THE_GEOM"]
    assert gdf.geometry.name == "THE_GEOM" and gdf.crs.to_epsg() == 4326
    assert gdf.geometry.iloc[2] is None and gdf["D"].isna().iloc[1]
    assert str(gdf["D"].dtype).startswith("datetime64")


def test_read_gdf_options(places):
    gdf = h2gis.read_gdf(places, "SELECT ID, ST_Buffer(THE_GEOM, 1) AS B, THE_GEOM FROM PLACE_NAMES "
                         "WHERE ID = %s", [1], geometry="THE_GEOM", crs="EPSG:3857")
    assert gdf.geometry.name == "THE_GEOM" and gdf.crs.to_epsg() == 3857
    assert gdf["B"].crs.to_epsg() == 4326
    empty = h2gis.read_gdf(places, "SELECT * FROM PLACE_NAMES WHERE ID < 0")
    assert len(empty) == 0 and list(empty.columns) == ["ID", "NOM", "D", "THE_GEOM"]
    with pytest.raises(errors.ProgrammingError, match="no GEOMETRY"):
        h2gis.read_gdf(places, "SELECT ID FROM PLACE_NAMES")
    with pytest.raises(errors.ProgrammingError, match="upper-cases"):
        h2gis.read_gdf(places, "SELECT * FROM PLACE_NAMES", geometry="the_geom")
    chunks = list(h2gis.read_gdf(places, "SELECT * FROM PLACE_NAMES ORDER BY ID", chunksize=2))
    assert [len(c) for c in chunks] == [2, 1]
    assert all(c.crs.to_epsg() == 4326 for c in chunks)
    df = h2gis.read_df(places, "SELECT ID, NOM FROM PLACE_NAMES ORDER BY ID")
    assert df["NOM"].tolist() == ["Paris", "Lyon", "No name"]


def test_read_df_decimals(conn):
    conn.execute("CREATE TABLE D(V NUMERIC(10, 3))")
    conn.execute("INSERT INTO D VALUES (1.125), (NULL)")
    df = h2gis.read_df(conn, "SELECT V FROM D ORDER BY V NULLS LAST")
    assert str(df["V"].dtype) == "float64" and df["V"].iloc[0] == 1.125 and df["V"].isna().iloc[1]
    exact = h2gis.read_df(conn, "SELECT V FROM D ORDER BY V NULLS LAST", coerce_float=False)
    assert exact["V"].iloc[0] == decimal.Decimal("1.125") and exact["V"].iloc[1] is None


def test_to_h2gis_roundtrip(places):
    import geopandas as gpd
    import numpy as np
    src = h2gis.read_gdf(places, "SELECT * FROM PLACE_NAMES ORDER BY ID")
    src["SCORE"] = [1.5, np.nan, 3.0]
    src["ok"] = [True, False, True]
    n = h2gis.to_h2gis(src, "copie", places, spatial_index=True)
    assert n == 3
    back = h2gis.read_gdf(places, "SELECT * FROM COPIE ORDER BY ID")
    assert list(back.columns) == ["ID", "NOM", "D", "THE_GEOM", "SCORE", "OK"]
    assert back.crs.to_epsg() == 4326 and back.geometry.iloc[2] is None
    assert back.geometry.iloc[0].equals(src.geometry.iloc[0])
    assert back["SCORE"].tolist()[0] == 1.5 and back["NOM"].tolist() == src["NOM"].tolist()
    assert places.execute("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE "
                          "TABLE_NAME = 'COPIE' AND COLUMN_NAME = 'THE_GEOM'").fetchone()[0] == "GEOMETRY"
    assert places.execute("SELECT COUNT(*) FROM COPIE WHERE SCORE IS NULL").fetchone() == (1,)
    with pytest.raises(errors.DuplicateTable):
        h2gis.to_h2gis(src, "copie", places)
    h2gis.to_h2gis(src, "copie", places, if_exists="append")
    assert places.execute("SELECT COUNT(*) FROM COPIE").fetchone() == (6,)
    h2gis.to_h2gis(src.iloc[:1], "copie", places, if_exists="replace")
    assert places.execute("SELECT COUNT(*) FROM COPIE").fetchone() == (1,)
    gdf = gpd.GeoDataFrame({"v": range(1200)}, geometry=gpd.points_from_xy(range(1200), range(1200)),
                           crs="EPSG:2154")
    assert h2gis.to_h2gis(gdf, sql.Identifier("Mixed Case"), places, chunksize=250) == 1200
    assert places.execute('SELECT COUNT(*), MAX(ST_SRID(GEOMETRY)) FROM "Mixed Case"').fetchone() == (1200, 2154)


def test_delete_database(lib_path, tmp_path):
    conn = h2gis.connect(tmp_path / "gone", lib_path=lib_path)
    conn.execute("CREATE TABLE A(X INT)")
    conn.delete_database()
    assert conn.closed and not (tmp_path / "gone.mv.db").exists()
