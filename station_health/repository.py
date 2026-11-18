"""SQL access. Every function takes an open connection and returns domain types.

This is the only module that contains SQL. Routes call these functions; the
starvation rule never sees the database, only the plain objects returned here.
All queries use ``?`` placeholders, so values are never pasted into SQL text
(which prevents SQL injection).
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

# Domain types the queries return, plus the error raised for a bad config.
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
    # "SELECT 1" returns a single dummy column: we only care whether a row
    # exists. Filtering by id AND operator_id in one query means MetroCycle
    # asking for Harbour's station 201 gets no row, exactly like station 999.
    row = connection.execute(
        "SELECT 1 FROM stations WHERE id = ? AND operator_id = ?",
        (station_id, operator_id),
    ).fetchone()

    # fetchone() returns None when no row matched.
    return row is not None


def get_operator_config(connection: sqlite3.Connection, operator_id: int) -> OperatorConfig:
    """Load the operator's rule: peak window (UTC) and minimum empty readings.

    Raises ``InvalidOperatorConfig`` if the operator has no config row or the
    stored values are unusable; routes.py turns that into a 500 response.
    """
    # Read the operator's single configuration row.
    row = connection.execute(
        """
        SELECT peak_start, peak_end, min_empty_readings
        FROM operator_configs
        WHERE operator_id = ?
        """,
        (operator_id,),
    ).fetchone()

    # An operator without a config cannot be evaluated; report it loudly
    # rather than guessing a default.
    if row is None:
        raise InvalidOperatorConfig(f"operator {operator_id}: no configuration row")

    # Convert the stored text ("08:00") into validated Python values.
    # Rows can be read by column name because db.connect() sets sqlite3.Row.
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
    # Build loose date bounds as plain ISO dates, for example for a window on
    # 2026-09-15: lower "2026-09-14", upper "2026-09-17" (exclusive). ISO
    # dates sort correctly as text, so ">=" and "<" work on the TEXT column.
    lower = (window.start.date() - timedelta(days=1)).isoformat()
    upper = (window.end.date() + timedelta(days=2)).isoformat()

    # Fetch this station's readings between the loose bounds. The schema's
    # index on (station_id, recorded_at) makes this a fast range scan.
    # ORDER BY id gives a stable order (oldest inserted first).
    rows = connection.execute(
        """
        SELECT id, station_id, recorded_at, bikes_available, docks_total
        FROM dock_readings
        WHERE station_id = ? AND recorded_at >= ? AND recorded_at < ?
        ORDER BY id
        """,
        (station_id, lower, upper),
    ).fetchall()

    # Turn each database row into a Reading object. dict(row) gives
    # {"id": ..., "station_id": ..., ...}, and ** passes those as arguments.
    return [Reading(**dict(row)) for row in rows]
