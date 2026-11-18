"""HTTP layer: validates input, wires the layers together and maps errors."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from station_health.auth import get_current_operator
from station_health.dependencies import Settings, get_settings, open_connection
from station_health.repository import (
    find_operator_station,
    get_operator_config,
    get_readings,
)
from station_health.schemas import ExcludedReadings, PeakWindowOut, StarvationResponse
from station_health.starvation import (
    InvalidOperatorConfig,
    evaluate_starvation,
    peak_window_for,
)

logger = logging.getLogger(__name__)

router = APIRouter()

STATION_NOT_FOUND = "Station not found"
CONFIG_INVALID = "Operator configuration invalid"

# The window may end a day after ``date`` and the readings query widens it by
# one more day on each side; these bounds keep every derived date representable.
MIN_DATE = date.min + timedelta(days=1)
MAX_DATE = date.max - timedelta(days=3)
# SQLite INTEGER is a signed 64-bit value; larger ids would raise OverflowError.
MAX_STATION_ID = 2**63 - 1
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


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


@router.get("/stations/{station_id}/starvation", response_model=StarvationResponse)
def get_station_starvation(
    station_id: Annotated[int, Path(ge=1, le=MAX_STATION_ID)],
    date_text: Annotated[
        str,
        Query(alias="date", pattern=DATE_PATTERN, description="Day to check, YYYY-MM-DD (UTC)"),
    ],
    operator_id: Annotated[int, Depends(get_current_operator)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StarvationResponse:
    """Report whether the station met its operator's starvation rule on ``date``."""
    day = parse_query_date(date_text)
    with open_connection(settings.database_path) as connection:
        # One scoped query and one response for "missing" and "another
        # operator's": callers cannot learn whether a foreign station exists.
        # Nothing else about the station is read before this check passes.
        if not find_operator_station(connection, operator_id, station_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, STATION_NOT_FOUND)
        try:
            config = get_operator_config(connection, operator_id)
        except InvalidOperatorConfig as exc:
            logger.error("Cannot evaluate starvation: %s", exc)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, CONFIG_INVALID) from exc
        readings = get_readings(connection, station_id, peak_window_for(config, day))

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
