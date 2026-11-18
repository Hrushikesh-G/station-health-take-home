"""HTTP layer: validates input, wires the layers together and maps errors.

The endpoint defined here is the only place that knows about every other
module. Its job, in order:

1. FastAPI runs authentication first (``get_current_operator``)  -> 401
2. validate ``station_id`` and ``date``                          -> 422
3. open the database                                             -> 503
4. confirm the operator owns the station                         -> 404
5. load the operator's rule and the station's readings           -> 500 if the rule is broken
6. apply the rule (``evaluate_starvation``) and return the JSON  -> 200
"""

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

# Logger named "station_health.routes".
logger = logging.getLogger(__name__)

# A router groups endpoints; app.py attaches it to the application.
router = APIRouter()

# Error messages, defined once so responses (and tests) always match exactly.
STATION_NOT_FOUND = "Station not found"
CONFIG_INVALID = "Operator configuration invalid"
DATABASE_UNAVAILABLE = "Database not initialised"

# The window may end a day after ``date`` and the readings query widens it by
# one more day on each side; these bounds keep every derived date representable.
# Supported range: 0001-01-02 to 9999-12-28.
MIN_DATE = date.min + timedelta(days=1)
MAX_DATE = date.max - timedelta(days=3)

# SQLite INTEGER is a signed 64-bit value; larger ids would raise OverflowError.
MAX_STATION_ID = 2**63 - 1

# Exactly four digits, dash, two digits, dash, two digits ("2026-09-15").
# [0-9] is used rather than \d, which would also match non-ASCII digits.
DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"


def _error(description: str, detail: str) -> dict:
    """Describe one error response for the OpenAPI document (/docs)."""
    return {
        "model": ErrorResponse,
        "description": description,
        "content": {"application/json": {"example": {"detail": detail}}},
    }


# The error responses this endpoint can return, listed for /docs. FastAPI adds
# the 422 validation response automatically.
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
    # The pattern already guaranteed the shape; this checks it is a real
    # calendar date (rejects 2026-02-30, 2026-13-01).
    try:
        day = date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "date must be a real calendar date in YYYY-MM-DD format",
        ) from exc

    # Reject the extreme years where window maths would overflow.
    if not MIN_DATE <= day <= MAX_DATE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"date must be between {MIN_DATE.isoformat()} and {MAX_DATE.isoformat()}",
        )
    return day


# Register GET /stations/{station_id}/starvation. response_model makes FastAPI
# validate and document the 200 body; the other arguments only affect /docs.
@router.get(
    "/stations/{station_id}/starvation",
    response_model=StarvationResponse,
    responses=ERROR_RESPONSES,
    summary="Check whether a station met the starvation rule on a date",
    tags=["stations"],
)
# A plain "def" (not "async def") makes FastAPI run this in a worker thread,
# so the blocking SQLite calls below do not stall other requests.
def get_station_starvation(
    # From the URL path. Must be an integer from 1 to 2^63-1, otherwise 422.
    station_id: Annotated[int, Path(ge=1, le=MAX_STATION_ID, description="Station id")],
    # From the query string "?date=...". Kept as text and checked against
    # DATE_PATTERN so lenient forms such as "1694736000" get a 422.
    date_text: Annotated[
        str,
        Query(alias="date", pattern=DATE_PATTERN, description="Day to check, YYYY-MM-DD (UTC)"),
    ],
    # Dependencies: FastAPI runs these before the function body. Authentication
    # runs before parameter validation, so a bad token always gets 401 first.
    operator_id: Annotated[int, Depends(get_current_operator)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StarvationResponse:
    """Report whether the station met its operator's starvation rule on ``date``.

    The station is starved when it has at least the operator's minimum number
    of in-service readings with zero bikes inside the operator's UTC peak
    window, start included and end excluded.
    """
    # Strict date check (422 on failure).
    day = parse_query_date(date_text)

    # Load everything needed from the database, translating failures into
    # HTTP responses. A 404 raised inside _load_inputs passes straight through.
    try:
        config, readings = _load_inputs(settings, operator_id, station_id, day)
    except DatabaseUnavailable as exc:
        # The database file is missing: tell the caller the service is not ready.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, DATABASE_UNAVAILABLE) from exc
    except InvalidOperatorConfig as exc:
        # The operator's rule is broken: log the detail for the team, but
        # return only a generic message to the caller.
        logger.error("Cannot evaluate starvation: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, CONFIG_INVALID) from exc

    # Apply the rule. This is pure Python with no database access.
    result = evaluate_starvation(readings, config, day)

    # Copy the result into the response model that becomes the JSON body.
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
    """Check ownership, then load the operator's rule and the station's readings.

    Raises a 404 HTTPException for a station the operator does not own,
    ``DatabaseUnavailable`` or ``InvalidOperatorConfig``; the caller maps the
    last two to 503 and 500.
    """
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

        # The operator's own window and threshold (raises if invalid).
        config = get_operator_config(connection, operator_id)

        # The station's readings around that window; exact filtering happens
        # later in evaluate_starvation.
        readings = get_readings(connection, station_id, peak_window_for(config, day))

    # The connection is closed here; return plain data for the rule.
    return config, readings
