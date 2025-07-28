# h2gis-python

A lib thal allows to interract with a h2gis lib. Do not forget when you create an H2gisConnection object to put the lib.so full path as a parameter. Without this, it will not work.

To insall run :
```
 python setup.py bdist_wheel
 pip install dist/h2gis-<version>-py3-none-any.whl  --force-reinstall
```

To publish the package, remove old builds from the dist folder then run :
```
twine upload dist/*
````