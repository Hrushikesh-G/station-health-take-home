"""Shared pytest fixtures.

pytest loads this file automatically. A *fixture* is a function that prepares
something a test needs; a test asks for it by naming it as a parameter
(``def test_x(client): ...``). Each test gets its own fresh copy.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seed import build_database
from station_health.app import app
from station_health.dependencies import Settings, get_settings


# Supplied fixture: builds a brand-new seeded database inside pytest's
# temporary folder (tmp_path is unique per test), so tests never touch the
# real station_health.db and cannot affect each other.
@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return build_database(tmp_path / "station_health.db")


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    """A client whose requests read the per-test seeded database.

    TestClient sends HTTP requests to the app in-process, with no real server.
    """
    # Replace the app's settings so every request reads this test's database
    # instead of the real file.
    app.dependency_overrides[get_settings] = lambda: Settings(database_path=database_path)
    try:
        # Hand the client to the test; the code after "yield" runs once the
        # test has finished.
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # Undo the override so the next test starts clean.
        app.dependency_overrides.pop(get_settings, None)
