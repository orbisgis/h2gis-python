from setuptools import find_packages, setup

setup(
    name='h2gis',
    version='0.0.2',
    description='A Python library to use an H2GIS database through a native GraalVM bridge.',
    long_description=open("docs/index.md").read(),
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
