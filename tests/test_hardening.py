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


# --- NFR-09: invalid operator configuration fails loudly --------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE operator_configs SET peak_end = peak_start WHERE operator_id = 1",
        "UPDATE operator_configs SET peak_start = 'eight' WHERE operator_id = 1",
        "DELETE FROM operator_configs WHERE operator_id = 1",
    ],
)
def test_invalid_operator_config_returns_500_and_is_logged(
    client: TestClient, database_path: Path, caplog: pytest.LogCaptureFixture, sql: str
) -> None:
    execute(database_path, sql)

    with caplog.at_level(logging.ERROR, logger="station_health"):
        response = client.get(
            "/stations/101/starvation", params={"date": SEED_DATE}, headers=METRO
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Operator configuration invalid"}
    assert any("operator 1" in r.getMessage() for r in caplog.records)
