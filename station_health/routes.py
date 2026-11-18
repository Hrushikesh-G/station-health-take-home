"""HTTP layer: validates input, wires the layers together and maps errors."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from station_health.auth import get_current_operator
from station_health.dependencies import Settings, get_settings, open_connection
from station_health.repository import (
    find_operator_station,
    get_operator_config,
    get_readings,
)
from station_health.schemas import ExcludedReadings, PeakWindowOut, StarvationResponse
from station_health.starvation import evaluate_starvation, peak_window_for

router = APIRouter()

STATION_NOT_FOUND = "Station not found"


@router.get("/stations/{station_id}/starvation", response_model=StarvationResponse)
def get_station_starvation(
    station_id: int,
    day: Annotated[date, Query(alias="date", description="Day to check, YYYY-MM-DD (UTC)")],
    operator_id: Annotated[int, Depends(get_current_operator)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StarvationResponse:
    """Report whether the station met its operator's starvation rule on ``date``."""
    with open_connection(settings.database_path) as connection:
        # One scoped query and one response for "missing" and "another
        # operator's": callers cannot learn whether a foreign station exists.
        # Nothing else about the station is read before this check passes.
        if not find_operator_station(connection, operator_id, station_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, STATION_NOT_FOUND)
        config = get_operator_config(connection, operator_id)
        readings = get_readings(connection, station_id, peak_window_for(config, day))

    result = evaluate_starvation(readings, config, day)
    return StarvationResponse(
        station_id=station_id,
        date=day,
        starved=result.starved,
        empty_reading_count=result.empty_reading_count,
        min_empty_readings=result.min_empty_readings,
        peak_window=PeakWindowOut(start=result.window.start, end=result.window.end),
        readings_in_window=result.readings_in_window,
        excluded_readings=ExcludedReadings(
            duplicates=result.duplicates,
            out_of_service=result.out_of_service,
        ),
    )
