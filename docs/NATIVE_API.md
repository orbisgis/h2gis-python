# Native library

h2gis-python runs H2GIS through a shared library built with GraalVM Native
Image (Mandrel) from the
[`h2gis-graalvm`](https://github.com/orbisgis/h2gis/tree/master/h2gis-graalvm)
module of H2GIS. Its C interface, the result buffer format and the memory
rules are documented there, in
[`C_API.md`](https://github.com/orbisgis/h2gis/blob/master/h2gis-graalvm/C_API.md).

## Requirements

- **C API version 2 or later** (`h2gis_version()`, H2GIS 2.2.6 and later).
  `connect()` refuses older libraries, such as the one of h2gis-python 0.0.x,
  with an `InterfaceError`.
- Linux x86-64 with glibc 2.34 or later, Windows x86-64, macOS on Apple silicon.

```python
with h2gis.connect("mem:") as conn:
    print(conn.native_version, conn.lib_path)
```

## Versions of H2

The library embeds one version of H2, which does not read the database files
of some other versions of H2. For example a database written by H2 2.4.240 is reported as
corrupted by H2 2.5.252 (error 90030), both versions writing the same file
format number. `h2gis.native_versions()` tells the versions built into the
library, without opening a database:

```python
>>> h2gis.native_versions()
{'cApi': 4, 'h2gis': '2.2.6', 'h2': '2.5.252', 'jts': '1.20.0'}
```

It uses `h2gis_get_versions()` (C API 4), or asks H2 with an older library
(no `jts` then). `Connection.native_versions` gives the same.

When `connect()` fails on a database written by another version of H2 (error
90030 or 90048), the `DatabaseError` says so, with the versions of the
library: write the database with the same version of H2, or migrate it
(`SCRIPT TO` with its own version of H2, then `RUNSCRIPT FROM` in a database
created by h2gis).

To migrate the database uses the H2 java implementation.

[H2MigrationTool](https://github.com/manticore-projects/H2MigrationTool) is
another way to migrate a database between versions of H2.

```bash
java -cp h2-2.4.240.jar org.h2.tools.Shell -url jdbc:h2:/path/to/mydb -user sa -sql "SELECT H2VERSION()"
ogrinfo -ro mydb.mv.db
```

## Choosing the library

1. `lib_path=` argument of `h2gis.connect()`
2. `H2GIS_LIB_PATH` environment variable
3. `h2gis/lib/h2gis.so` (`.dll`, `.dylib`) inside the package (installed wheel)
4. `native/<platform>/h2gis.<ext>` of the repository, when h2gis runs from a
   clone (`pip install -e .`); see [native/README.md](../native/README.md)

All the connections of a process share one library and one GraalVM isolate.
Two different native libraries can't be loaded in the same process: their
`graal_*` symbols collide.

## How the driver uses it

| Driver | Native functions |
|---|---|
| `connect()` / `close()` | `h2gis_connect`, `h2gis_close_connection` |
| `execute()` without parameters | `h2gis_execute` or `h2gis_fetch` |
| `execute()` with parameters | `h2gis_prepare`, `h2gis_bind_*`, `h2gis_execute_prepared[_update]` |
| `executemany()` | `h2gis_prepare`, `h2gis_bind_*`, `h2gis_add_batch`, `h2gis_execute_batch` |
| `to_h2gis()` | multi-row `INSERT ... VALUES (?, ...), (?, ...)` prepared statements (faster than batches here) |
| `fetch*()`, `read_gdf()` | `h2gis_fetch_all`, `h2gis_get_metadata_json` |
| `stream()`, `read_gdf(chunksize=)` | `h2gis_fetch_batch` |
| errors | `h2gis_get_last_error` |
| threads | `graal_attach_thread` / `graal_detach_thread` per Python thread |

The statement type (query or update) is guessed from the first keyword; when
the guess is wrong, H2 reports error 90001/90002 and the driver retries with
the other function.

## Building the library

With Maven (what the H2GIS CI does):

```bash
mvn clean package -DskipTests && mvn native:compile -Pnative -pl h2gis-graalvm -DskipTests
```

Without Maven Central, from the jars of an H2GIS release and Mandrel:

```bash
M=/path/to/mandrel
curl -LO https://github.com/orbisgis/h2gis/releases/download/v2.2.5/h2gis-standalone-bin.zip
unzip h2gis-standalone-bin.zip
CP=$(find h2gis-standalone -name '*.jar' ! -name '*osgi*' | tr '\n' ':')
API=$(ls $M/lib/jvmci/*.jar | tr '\n' ':')     # org.graalvm.nativeimage API
$M/bin/javac -d classes -cp "$API$CP" h2gis-graalvm/src/main/java/org/h2gis/graalvm/*.java
cp -r h2gis-graalvm/src/main/resources/META-INF classes/
$M/bin/native-image -cp "classes:$CP" -o h2gis --shared -march=compatibility \
  -H:+AllowFoldMethods --enable-url-protocols=http,https,tcp \
  --report-unsupported-elements-at-runtime --initialize-at-run-time=org.h2,org.h2gis \
  --features=org.h2gis.graalvm.GraalCInterfaceEntryPointFeature \
  -H:ResourceConfigurationFiles=classes/META-INF/native-image/resource-config.json \
  -H:ReflectionConfigurationResources=META-INF/native-image/reflect-config.json
```

About 7 minutes and 3.5 GB of RAM on 2 cores; the Linux library is ~80 MB.
