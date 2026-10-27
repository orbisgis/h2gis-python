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

# Import a GeoJSON file with H2GIS, read it in batches and write a result back.
#
#     python example-2.py /path/to/my_db [test.geojson]

import os
import sys

import matplotlib.pyplot as plt

import h2gis
from h2gis import sql

db_path = sys.argv[1] if len(sys.argv) > 1 else "./example_db"
geojson = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "test.geojson")

with h2gis.connect(db_path) as conn:
    conn.execute("DROP TABLE IF EXISTS TEST")
    # H2GIS functions are called like any SQL; the path is a bound parameter
    conn.execute("CALL GeoJsonRead(%s, 'TEST')", [os.path.abspath(geojson)])
    count, srid = conn.execute("SELECT COUNT(*), MAX(ST_SRID(THE_GEOM)) FROM TEST").fetchone()
    print(f"{count} features imported, SRID {srid}")

    # Large tables: read in batches of 100 000 rows
    n = 0
    for chunk in h2gis.read_gdf(conn, "SELECT THE_GEOM FROM TEST", chunksize=100_000):
        n += len(chunk)
    print(f"{n} rows read in batches")

    # Work in SQL, then get the result as a GeoDataFrame. The CRS comes from the
    # SRID of the geometries; GeoJsonRead leaves it to 0, so give it explicitly.
    gdf = h2gis.read_gdf(conn, """
        SELECT ST_GeometryType(THE_GEOM) AS TYPE, COUNT(*) AS N,
               ST_Envelope(ST_Accum(THE_GEOM)) AS THE_GEOM
        FROM TEST GROUP BY ST_GeometryType(THE_GEOM)""", crs="EPSG:4326")
    print(gdf)

    # Write a GeoDataFrame back to the database
    h2gis.to_h2gis(gdf, "TEST_ENVELOPES", conn, if_exists="replace")  # GEOMETRY(POLYGON, 4326)
    table = sql.Identifier("TEST_ENVELOPES")
    print(conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(table)).fetchone()[0],
          "rows written")

gdf.plot(column="TYPE", legend=True, alpha=0.5)
plt.show()
