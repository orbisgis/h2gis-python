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

@author Maël PHILIPPE
@author Erwan BOCHER
"""

import os
import sys
from h2gis import H2GIS
import geopandas as gpd
import pandas as pd
from shapely.wkt import loads as wkt_loads
import json

import time

# Connexion et import des données
h2gis = H2GIS("/home/mael/test", "sa", "sa")

# Nettoyage des tables si elles existent
h2gis.execute("DROP TABLE IF EXISTS TEST;")

h2gis.execute("CALL GeoJsonRead('./test.geojson');")

fetch = h2gis.fetch("SELECT THE_GEOM FROM TEST;")

gdf = gpd.GeoDataFrame(fetch, geometry="THE_GEOM", crs="EPSG:2154")

# Print dataframe
gdf.plot()

# Close the connetion
h2gis.close()
