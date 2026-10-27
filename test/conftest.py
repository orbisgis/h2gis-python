"""
Integration tests run against every native library listed in
``$H2GIS_TEST_LIBS`` (paths separated by os.pathsep), or against the bundled
``h2gis/lib/h2gis.<ext>``. They are skipped when no library is available.
"""

import os

import pytest

from h2gis._native import default_library_path


def _libs():
    env = os.environ.get("H2GIS_TEST_LIBS")
    paths = [p for p in env.split(os.pathsep) if p] if env else [default_library_path()]
    return [p for p in paths if os.path.exists(p)]


LIBS = _libs()


@pytest.fixture(params=LIBS or [None], ids=lambda p: os.path.basename(os.path.dirname(p)) if p else "none")
def lib_path(request):
    if request.param is None:
        pytest.skip("no native H2GIS library (set H2GIS_TEST_LIBS)")
    return request.param


@pytest.fixture
def conn(lib_path, tmp_path):
    import h2gis
    c = h2gis.connect(tmp_path / "db", lib_path=lib_path)
    yield c
    c.close()
