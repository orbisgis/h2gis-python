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

from setuptools import find_packages, setup

setup(
    name='h2gis',
    version='0.0.2',
    description='A Python library to use an H2GIS database through a native GraalVM bridge.',
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author='Lemap',
    url='https://github.com/orbisgis/h2gis',  # Replace with actual URL
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "h2gis": ["lib/*.so", "lib/*.dll", "lib/*.dylib"],
        "h2gis.docs": ["*.md"],  # add this if docs is inside the h2gis package
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    setup_requires=['pytest-runner', 'shapely'],
    tests_require=['pytest==4.4.1']
)
