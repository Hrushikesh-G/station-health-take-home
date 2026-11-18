"""API-level tests for the gap-closure requirements (NFR-06 to NFR-15)."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

METRO = {"Authorization": "Bearer metro-token"}
SEED_DATE = "2026-09-15"


def starvation(client: TestClient, station_id: int = 101, date: str = SEED_DATE) -> dict:
    response = client.get(
        f"/stations/{station_id}/starvation", params={"date": date}, headers=METRO
    )
    assert response.status_code == 200, response.text
    return response.json()


def execute(database_path: Path, sql: str, params: tuple = ()) -> None:
    """Change the per-test temporary database only; seed.py is never touched."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(sql, params)
    connection.close()


# --- NFR-08: an unparseable timestamp never breaks a request ----------------


def test_unparseable_reading_is_skipped_and_logged(
    client: TestClient, database_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    baseline = starvation(client)
    # Sorts inside the SQL range, so it is fetched, but hour 25 is invalid.
    execute(
        database_path,
        "INSERT INTO dock_readings (station_id, recorded_at, bikes_available, docks_total) "
        "VALUES (101, '2026-09-15T25:00:00+00:00', 0, 12)",
    )

    with caplog.at_level(logging.WARNING, logger="station_health"):
        assert starvation(client) == baseline

    assert any("unparseable recorded_at" in r.getMessage() for r in caplog.records)
