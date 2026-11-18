from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seed import build_database
from station_health.app import app
from station_health.dependencies import Settings, get_settings


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return build_database(tmp_path / "station_health.db")


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    """A client whose requests read the per-test seeded database."""
    app.dependency_overrides[get_settings] = lambda: Settings(database_path=database_path)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_settings, None)
