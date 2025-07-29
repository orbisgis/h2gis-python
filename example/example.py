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

from h2gis import H2GIS
import geopandas as gpd
import pandas as pd
from shapely.wkt import loads as wkt_loads
import json
import matplotlib.pyplot as plt  # Import matplotlib
import ast

# Connexion and data import
h2gis = H2GIS("/mydb/path/dbName", "sa", "sa")
h2gis.execute("""
        DROP TABLE IF EXISTS LIEUX;
        CREATE TABLE LIEUX (
            ID INT PRIMARY KEY AUTO_INCREMENT,
            NOM VARCHAR(255),
            DESCRIPTION VARCHAR(255),
            THE_GEOM GEOMETRY(GEOMETRY)
        );
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Paris', 'Capitale de la France', ST_GeomFromText('POINT(2.3522 48.8566)', 4326));
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Lyon', 'Ville gastronomique', ST_GeomFromText('POINT(4.8357 45.7640)', 4326));
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Marseille', 'Port méditerranéen', ST_GeomFromText('POINT(5.3698 43.2965)', 4326));
        INSERT INTO LIEUX (NOM, DESCRIPTION, THE_GEOM) VALUES ('Englobant', 'Géométrie englobante', ST_GeomFromText('POLYGON((
        -4.72 48.42,
        -1.35 47.23,
        0.88 47.90,
        2.35 48.86,
        4.08 49.33,
        5.70 49.00,
        6.65 48.16,
        7.75 48.58,
        7.27 47.50,
        6.75 46.15,
        6.00 45.45,
        4.90 44.50,
        4.20 43.80,
        5.3698 43.2965,
        3.50 43.00,
        2.50 42.50,
        0.50 42.80,
        -1.00 43.40,
        -1.80 44.50,
        -2.50 45.80,
        -2.90 46.80,
        -3.50 47.80,
        -4.72 48.42
    ))', 4326)
);
""")

# Fetch
fetch = h2gis.fetch("SELECT NOM, DESCRIPTION, THE_GEOM as geometry FROM LIEUX;")
print(fetch)

# Convert as dataframe
gdf = gpd.GeoDataFrame(fetch, geometry="GEOMETRY", crs="EPSG:4326")
print(gdf)

# Gest distance between first two points
if len(gdf) >= 2:
    paris_geom = gdf[gdf['NOM'] == 'Paris'].geometry.iloc[0]
    lyon_geom = gdf[gdf['NOM'] == 'Lyon'].geometry.iloc[0]
    dist_paris_lyon = paris_geom.distance(lyon_geom) * 111319.9

    print(f"Distance in meters between poit 1 and 2: {dist_paris_lyon:.2f} m")
else:
    print("2 geometries needed to calculate a distance")

print("connected : ", h2gis.isConnected())
h2gis.close()

# Display data
gdf.plot(edgecolor='black', figsize=(10, 8))
plt.xlabel("Longitude")
plt.ylabel("Latitude")
plt.show()
