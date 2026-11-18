"""SQL access. Every function takes an open connection and returns domain types."""

from __future__ import annotations

import sqlite3

from station_health.starvation import OperatorConfig


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
        raise LookupError(f"operator {operator_id} has no configuration")
    return OperatorConfig.from_row(
        operator_id,
        row["peak_start"],
        row["peak_end"],
        row["min_empty_readings"],
    )
