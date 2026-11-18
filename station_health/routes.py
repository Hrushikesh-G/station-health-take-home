"""HTTP layer: validates input, wires the layers together and maps errors."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from station_health.auth import get_current_operator
from station_health.dependencies import (
    DatabaseUnavailable,
    Settings,
    get_settings,
    open_connection,
)
from station_health.repository import (
    find_operator_station,
    get_operator_config,
    get_readings,
)
from station_health.schemas import (
    ErrorResponse,
    ExcludedReadings,
    PeakWindowOut,
    StarvationResponse,
)
from station_health.starvation import (
    InvalidOperatorConfig,
    OperatorConfig,
    Reading,
    evaluate_starvation,
    peak_window_for,
)

logger = logging.getLogger(__name__)

router = APIRouter()

STATION_NOT_FOUND = "Station not found"
CONFIG_INVALID = "Operator configuration invalid"
DATABASE_UNAVAILABLE = "Database not initialised"

# The window may end a day after ``date`` and the readings query widens it by
# one more day on each side; these bounds keep every derived date representable.
MIN_DATE = date.min + timedelta(days=1)
MAX_DATE = date.max - timedelta(days=3)
# SQLite INTEGER is a signed 64-bit value; larger ids would raise OverflowError.
MAX_STATION_ID = 2**63 - 1
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def _error(description: str, detail: str) -> dict:
    return {
        "model": ErrorResponse,
        "description": description,
        "content": {"application/json": {"example": {"detail": detail}}},
    }


ERROR_RESPONSES: dict[int | str, dict] = {
    401: _error("Missing, malformed or unknown bearer token", "Not authenticated"),
    404: _error("Station does not exist or belongs to another operator", STATION_NOT_FOUND),
    500: _error("The operator's configuration is missing or invalid", CONFIG_INVALID),
    503: _error("The database has not been created; run `python seed.py`", DATABASE_UNAVAILABLE),
}


def parse_query_date(value: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` date or raise 422.

    The query parameter is declared as text with a pattern because FastAPI's
    ``date`` coercion also accepts Unix timestamps and full datetimes, which
    would silently answer for a different day.
    """
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "date must be a real calendar date in YYYY-MM-DD format",
        ) from exc
    if not MIN_DATE <= day <= MAX_DATE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"date must be between {MIN_DATE.isoformat()} and {MAX_DATE.isoformat()}",
        )
    return day


@router.get(
    "/stations/{station_id}/starvation",
    response_model=StarvationResponse,
    responses=ERROR_RESPONSES,
    summary="Check whether a station met the starvation rule on a date",
    tags=["stations"],
)
def get_station_starvation(
    station_id: Annotated[int, Path(ge=1, le=MAX_STATION_ID, description="Station id")],
    date_text: Annotated[
        str,
        Query(alias="date", pattern=DATE_PATTERN, description="Day to check, YYYY-MM-DD (UTC)"),
    ],
    operator_id: Annotated[int, Depends(get_current_operator)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StarvationResponse:
    """Report whether the station met its operator's starvation rule on ``date``.

    The station is starved when it has at least the operator's minimum number
    of in-service readings with zero bikes inside the operator's UTC peak
    window, start included and end excluded.
    """
    day = parse_query_date(date_text)
    try:
        config, readings = _load_inputs(settings, operator_id, station_id, day)
    except DatabaseUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE) from exc
    except InvalidOperatorConfig as exc:
        logger.error("Cannot evaluate starvation: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, CONFIG_INVALID) from exc

    result = evaluate_starvation(readings, config, day)
    return StarvationResponse(
        station_id=station_id,
        date=day,
        starved=result.starved,
        empty_reading_count=result.empty_reading_count,
        min_empty_readings=result.min_empty_readings,
        peak_window=PeakWindowOut(start=result.window.start, end=result.window.end),
        data_status=result.data_status,
        readings_in_window=result.readings_in_window,
        excluded_readings=ExcludedReadings(
            duplicates=result.duplicates,
            out_of_service=result.out_of_service,
        ),
    )


def _load_inputs(
    settings: Settings, operator_id: int, station_id: int, day: date
) -> tuple[OperatorConfig, list[Reading]]:
    # Opened here rather than in a ``yield`` dependency: FastAPI may run a
    # dependency's setup and teardown on different worker threads, and sqlite3
    # connections refuse cross-thread use. This keeps the connection in one
    # thread from open to close.
    with open_connection(settings.database_path) as connection:
        # One scoped query and one response for "missing" and "another
        # operator's": callers cannot learn whether a foreign station exists.
        # Nothing else about the station is read before this check passes.
        if not find_operator_station(connection, operator_id, station_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, STATION_NOT_FOUND)
        config = get_operator_config(connection, operator_id)
        readings = get_readings(connection, station_id, peak_window_for(config, day))
    return config, readings
