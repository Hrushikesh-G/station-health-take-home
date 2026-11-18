from __future__ import annotations

import sqlite3
from datetime import time
from pathlib import Path

import pytest

from station_health.dependencies import Settings, get_settings, open_connection
from station_health.repository import get_operator_config
from station_health.starvation import OperatorConfig
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
