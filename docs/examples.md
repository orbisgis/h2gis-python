# Examples

This page gives some examples to use H2GIS. A runnable versions are in the [example](../example/) folder:
`example.py` ( with all CRUD operation create, insert, query, plot) and `example-2.py` (import a
GeoJSON file, read it in batches, write a result back).

## Insert with parameters, query, GeoPandas

```python
import h2gis
from h2gis.rows import dict_row

# Windows path h2gis.connect(r"C:\data\my_db",...
with h2gis.connect("/data/my_db", row_factory=dict_row) as conn:
    conn.execute("CREATE TABLE PLACE_NAMES(ID SERIAL, NOM VARCHAR, "
                 "THE_GEOM GEOMETRY(POINT, 4326))")
    conn.cursor().executemany(
        "INSERT INTO PLACE_NAMES(NOM, THE_GEOM) VALUES (%s, %s)",
        [("Paris", "SRID=4326;POINT (2.3522 48.8566)"),
         ("Lyon", "SRID=4326;POINT (4.8357, 45.7640)")])

    row = conn.execute("SELECT * FROM PLACE_NAMES WHERE NOM = %s", ["Lyon"]).fetchone()
    print(row["ID"], row["THE_GEOM"].wkt)

    gdf = h2gis.read_gdf(conn, "SELECT * FROM PLACE_NAMES")   # crs = EPSG:4326
```

## Spatial filter with a geometry parameter

```python
zone = "SRID=4326;POLYGON ((2 48, 3 48, 3 49, 2 49, 2 48))"
gdf = h2gis.read_gdf(conn, "SELECT * FROM PLACE_NAMES WHERE ST_Intersects(THE_GEOM, %s)", [zone])```
```

## Import a file with an H2GIS function

```python
conn.execute("CALL GeoJsonRead(%s, 'BATIMENTS')", ["/data/batiments.geojson"])
conn.execute("CALL SHPRead(%s, 'COMMUNES')", ["/data/communes.shp"])
```

## Read large tables

```python
for chunk in h2gis.read_gdf(conn, "SELECT * FROM BATIMENTS", chunksize=100_000):
    process(chunk)

cur = conn.cursor()
for row in cur.stream("SELECT ID, THE_GEOM FROM BATIMENTS", size=50_000):
    ...
```

## Dynamic table names

```python
from h2gis import sql

table = sql.Identifier("PUBLIC", "PLACE_NAMES")   # quoted: give the exact (upper) case
q = sql.SQL("SELECT COUNT(*) FROM {} WHERE NOM LIKE %s").format(table)
print(conn.execute(q, ["P%"]).fetchone())
```

## Transactions

```python
with conn.transaction():
    conn.execute("UPDATE PLACE_NAMES SET NOM = UPPER(NOM)")
    with conn.transaction():                  # savepoint
        conn.execute("DELETE FROM PLACE_NAMES")
        raise h2gis.Rollback                  # only the DELETE is undone
```

## Managing errors

```python
try:
    conn.execute("SELECT * FROM NOPE")
except h2gis.errors.UndefinedTable as e:
    print(e.h2_code, e.sqlstate, e)           # 42102 42S02 Table "NOPE" not found...
```

## Import from GeoDataFrame

```python
import geopandas as gpd

communes = gpd.read_file("communes.gpkg")
h2gis.to_h2gis(communes, "communes", conn, if_exists="replace", spatial_index=True)
# -> table COMMUNES, geometry column GEOMETRY(MULTIPOLYGON, <epsg of communes.crs>)
```
