# Changelog version 2.1.0


- h2gis.native_versions() and Connection.native_versions: the versions of H2GIS, H2 and JTS built into the native library (h2gis_get_versions() of the C API 4, or asked to H2 with an older library).
- Opening a database written by another version of H2 (errors 90030 and 90048) raises a DatabaseError that says so, with the versions of the library. The H2 code of an error is its last [code-build], no longer only at the end of the message.
