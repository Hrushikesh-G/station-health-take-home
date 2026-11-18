from __future__ import annotations

import sqlite3
from datetime import date, time
from pathlib import Path

import pytest

from station_health.dependencies import (
    DatabaseUnavailable,
    Settings,
    get_settings,
    open_connection,
)
from station_health.repository import find_operator_station, get_operator_config, get_readings
from station_health.starvation import OperatorConfig, peak_window_for, readings_in_window
from station_health.supplied import DATABASE_PATH


def test_default_settings_use_the_supplied_database_path() -> None:
    assert get_settings() == Settings(database_path=DATABASE_PATH)


def test_open_connection_reads_the_injected_database(database_path: Path) -> None:
    with open_connection(database_path) as connection:
        row = connection.execute("SELECT name FROM operators WHERE id = 1").fetchone()

    assert row["name"] == "MetroCycle"


def test_open_connection_closes_the_connection_on_exit(database_path: Path) -> None:
    with open_connection(database_path) as connection:
        pass

    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_open_connection_refuses_a_missing_file_without_creating_it(tmp_path: Path) -> None:
    missing = tmp_path / "missing.db"

    with pytest.raises(DatabaseUnavailable):
        with open_connection(missing):
            pass

    assert not missing.exists()


# --- FR-03: operator configuration ------------------------------------------


@pytest.mark.parametrize(
    ("operator_id", "expected"),
    [
        (1, OperatorConfig(1, time(8, 0), time(10, 0), 3)),
        (2, OperatorConfig(2, time(7, 30), time(9, 30), 2)),
    ],
)
def test_each_operator_loads_its_own_configuration(
    database_path: Path, operator_id: int, expected: OperatorConfig
) -> None:
    with open_connection(database_path) as connection:
        assert get_operator_config(connection, operator_id) == expected


# --- FR-04: candidate readings around the window ----------------------------


def test_get_readings_returns_every_candidate_for_the_window(database_path: Path) -> None:
    with open_connection(database_path) as connection:
        config = get_operator_config(connection, 1)
        window = peak_window_for(config, date(2026, 9, 15))
        candidates = get_readings(connection, 101, window)

    # All 8 rows for station 101 fall within the widened bounds, including
    # the 2026-09-14 reading; the exact filter keeps the 5 inside 08:00-10:00.
    assert len(candidates) == 8
    assert {reading.station_id for reading in candidates} == {101}
    assert [r.recorded_at[11:16] for r in readings_in_window(candidates, window)] == [
        "08:00",
        "08:15",
        "08:30",
        "08:45",
        "09:00",
    ]


# --- FR-08: stations are only visible to their operator ---------------------


@pytest.mark.parametrize(
    ("operator_id", "station_id", "visible"),
    [
        (1, 101, True),
        (1, 104, True),
        (1, 201, False),
        (2, 201, True),
        (2, 101, False),
        (1, 999, False),
    ],
)
def test_find_operator_station_is_scoped_to_the_operator(
    database_path: Path, operator_id: int, station_id: int, visible: bool
) -> None:
    with open_connection(database_path) as connection:
        assert find_operator_station(connection, operator_id, station_id) is visible
