# H2GIS Class

## Overview

`H2GIS` is a Python class that wraps a native shared library compiled with GraalVM. It provides access to an embedded H2GIS database using GraalVM isolate and thread objects.

## Constructor

```python
H2GIS(lib_path=None)
```

- `lib_path`: Optional path to the `.so`, `.dll`, or `.dylib` file. If not provided, a default path is used based on the current OS.

## Methods

### `connect(db_file: str, username="sa", password="")`

Connect to a local H2GIS database file.

### `execute(sql: str) -> int`

Execute an `INSERT`, `UPDATE`, or `DELETE` SQL statement.

### `fetch(sql: str) -> list[str]`

Execute a `SELECT` SQL query and return results as a list of strings (one per row).

### `close()`

Close the active database connection.

### `__del__()`

Destructor that automatically tears down the GraalVM isolate and closes any connection.
