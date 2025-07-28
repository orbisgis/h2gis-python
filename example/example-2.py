from h2gis import H2GIS
import geopandas as gpd
import pandas as pd
from shapely.wkt import loads as wkt_loads
import json
import matplotlib.pyplot as plt
import time

# Connection and data import
h2gis = H2GIS("/home/mael/test", "sa", "sa")

# Clean tables
h2gis.execute("DROP TABLE IF EXISTS TEST;")


h2gis.execute("CALL GeoJsonRead('./test.geojson');")

fetch = h2gis.fetch("SELECT * FROM TEST;")

# Convert in dataframe
df = pd.DataFrame(fetch)
df["geometry"] = df["THE_GEOM"].apply(wkt_loads)

# Create a gopandas dataframe
gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:2154")
print(gdf)

# Plot the geoms of the dataframe
gdf.plot()


# Close h2gis connection
h2gis.close()

plt.show()
