"""Response models for the HTTP API.

These Pydantic models define the exact JSON the endpoint returns. FastAPI uses
them to serialise the response and to generate the schema shown at /docs.
Field descriptions below appear there as documentation for API users.
"""

from __future__ import annotations

# Imported as "dt" so a field can be called "date" without clashing with the
# datetime.date type.
import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

# The enum of data status values ("ok", "no_data", "out_of_service").
from station_health.starvation import DataStatus


class PeakWindowOut(BaseModel):
    """The UTC window that was applied. Datetimes serialise like 2026-09-15T08:00:00Z."""

    start: dt.datetime = Field(description="Window start in UTC (included)")
    end: dt.datetime = Field(description="Window end in UTC (excluded)")


class ExcludedReadings(BaseModel):
    """Readings that were found but deliberately not counted, and why."""

    duplicates: int = Field(description="Rows dropped because another row has the same instant")
    out_of_service: int = Field(description="In-window readings with docks_total = 0")


class StarvationResponse(BaseModel):
    """The body of a successful (200) response."""

    # The example below is shown in /docs as a sample response.
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "station_id": 101,
                "date": "2026-09-15",
                "starved": True,
                "empty_reading_count": 3,
                "min_empty_readings": 3,
                "peak_window": {
                    "start": "2026-09-15T08:00:00Z",
                    "end": "2026-09-15T10:00:00Z",
                },
                "data_status": "ok",
                "readings_in_window": 5,
                "excluded_readings": {"duplicates": 0, "out_of_service": 0},
            }
        }
    )

    # Echo of the request, so a saved response explains itself.
    station_id: int
    date: dt.date

    # The answer, and the count that supports it.
    starved: bool = Field(description="True when empty_reading_count >= min_empty_readings")
    empty_reading_count: int = Field(
        description="Distinct in-service readings in the window with 0 bikes available"
    )

    # The rule that was applied, so anyone can check the answer.
    min_empty_readings: int = Field(description="The operator's threshold")
    peak_window: PeakWindowOut

    # How much data the answer rests on.
    data_status: DataStatus = Field(
        description="ok: in-service data exists; no_data: no readings; "
        "out_of_service: every reading had docks_total = 0"
    )
    readings_in_window: int = Field(description="Distinct in-service readings considered")
    excluded_readings: ExcludedReadings


class ErrorResponse(BaseModel):
    """The body of an error response, e.g. {"detail": "Station not found"}.

    Only used to document the 401/404/500/503 responses in /docs; FastAPI's
    HTTPException already produces this shape.
    """

    detail: str
