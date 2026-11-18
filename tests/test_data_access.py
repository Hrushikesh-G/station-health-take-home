from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from station_health.dependencies import Settings, get_settings, open_connection
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
