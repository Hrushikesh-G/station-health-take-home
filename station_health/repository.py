"""SQL access. Every function takes an open connection and returns domain types."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from station_health.starvation import (
    InvalidOperatorConfig,
    OperatorConfig,
    PeakWindow,
    Reading,
)


def find_operator_station(
    connection: sqlite3.Connection, operator_id: int, station_id: int
) -> bool:
    """True only if the station exists *and* belongs to the operator.

    Ownership is part of the WHERE clause, so a station owned by another
    operator is indistinguishable from one that does not exist.
    """
    row = connection.execute(
        "SELECT 1 FROM stations WHERE id = ? AND operator_id = ?",
        (station_id, operator_id),
    ).fetchone()
    return row is not None


def get_operator_config(connection: sqlite3.Connection, operator_id: int) -> OperatorConfig:
    row = connection.execute(
        """
        SELECT peak_start, peak_end, min_empty_readings
        FROM operator_configs
        WHERE operator_id = ?
        """,
        (operator_id,),
    ).fetchone()
    if row is None:
        raise InvalidOperatorConfig(f"operator {operator_id}: no configuration row")
    return OperatorConfig.from_row(
        operator_id,
        row["peak_start"],
        row["peak_end"],
        row["min_empty_readings"],
    )


def get_readings(
    connection: sqlite3.Connection, station_id: int, window: PeakWindow
) -> list[Reading]:
    """Candidate readings for ``window``; the exact filter is applied in Python.

    ``recorded_at`` is TEXT, so the bounds are compared as strings. They are
    widened by a day on each side: a UTC offset is always under 24 hours, so
    every row whose instant could fall inside the window is returned, and the
    (station_id, recorded_at) index is still used.
    """
    lower = (window.start.date() - timedelta(days=1)).isoformat()
    upper = (window.end.date() + timedelta(days=2)).isoformat()
    rows = connection.execute(
        """
        SELECT id, station_id, recorded_at, bikes_available, docks_total
        FROM dock_readings
        WHERE station_id = ? AND recorded_at >= ? AND recorded_at < ?
        ORDER BY id
        """,
        (station_id, lower, upper),
    ).fetchall()
    return [Reading(**dict(row)) for row in rows]
