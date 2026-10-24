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

@author Erwan BOCHER, CNRS
"""

# Create a table, insert places with parameters, query them and plot them
# with GeoPandas. Geometries are given as EWKT strings (SRID=4326;...).
#
#     python example.py /path/to/my_db

import sys

import matplotlib.pyplot as plt

import h2gis
from h2gis.rows import dict_row

db_path = sys.argv[1] if len(sys.argv) > 1 else "./example_db"

with h2gis.connect(db_path, row_factory=dict_row) as conn:
    conn.execute("DROP TABLE IF EXISTS PLACE_NAMES")
    conn.execute("""
                 CREATE TABLE PLACE_NAMES (
                                              ID SERIAL,
                                              NOM VARCHAR(255),
                                              DESCRIPTION VARCHAR(255),
                                              THE_GEOM GEOMETRY(GEOMETRY, 4326)
                 )""")

    places = [
        ("Paris", "Capitale de la France", "SRID=4326;POINT (2.3522 48.8566)"),
        ("Lyon", "Ville lumiere", "SRID=4326;POINT (4.8357 45.7640)"),
        ("Marseille", "Port méditerranéen", "SRID=4326;POINT (5.3698 43.2965)")
    ]
    # Parameters are bound by the driver: no string concatenation, no SQL injection.
    # H2 converts the EWKT strings to geometries, with their SRID.
    conn.cursor().executemany(
        "INSERT INTO PLACE_NAMES (NOM, DESCRIPTION, THE_GEOM) VALUES (%s, %s, %s)", places)

    # Rows as dicts, geometries come back as Shapely objects
    for row in conn.execute("SELECT NOM, ST_GeometryType(THE_GEOM) AS TYPE FROM PLACE_NAMES ORDER BY ID"):
        print(row["NOM"], row["TYPE"])

    # Distance computed by H2GIS, in Lambert 93 (EPSG:2154)
    paris_lyon = conn.execute("""
                              SELECT ST_Distance(ST_Transform(A.THE_GEOM, 2154), ST_Transform(B.THE_GEOM, 2154)) AS D
                              FROM PLACE_NAMES A, PLACE_NAMES B WHERE A.NOM = %s AND B.NOM = %s""", ["Paris", "Lyon"]).fetchone()
    print(f"Distance Paris - Lyon: {paris_lyon['D'] / 1000:.1f} km")

    # Straight to GeoPandas: the CRS comes from the SRID of the geometries
    gdf = h2gis.read_gdf(conn, "SELECT NOM, DESCRIPTION, THE_GEOM FROM PLACE_NAMES")
    print(gdf)
    print("CRS:", gdf.crs)
# committed and closed here

# The polygon in grey, the places as red points labelled with their name
points = gdf[gdf.geom_type == "Point"]
ax = gdf[gdf.geom_type != "Point"].plot(color="lightgrey", edgecolor="black", figsize=(10, 8))
points.plot(ax=ax, color="red", markersize=40)
for nom, geom in zip(points["NOM"], points.geometry):
    ax.annotate(nom, (geom.x, geom.y), xytext=(6, 6), textcoords="offset points", fontsize=11)
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.show()