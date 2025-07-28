# Installation

## Requirements

- Python 3.7+
- Native H2GIS shared library compiled with GraalVM
- Supported platforms: Linux, Windows, macOS

## Install the Python Package

```bash
pip install .
```

Ensure the native library file is present in the following structure:

```
h2gis/
├── lib/
│   ├── h2gis.so      # Linux
│   ├── h2gis.dylib   # macOS
│   └── h2gis.dll     # Windows
```

## Custom Library Path

You can specify a custom path to the native library:

```python
from h2gis import H2GIS

db = H2GIS(lib_path="/custom/path/to/h2gis.so")
```