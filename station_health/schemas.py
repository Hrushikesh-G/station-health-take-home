"""Response models for the HTTP API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from station_health.starvation import DataStatus


class PeakWindowOut(BaseModel):
    start: dt.datetime = Field(description="Window start in UTC (included)")
    end: dt.datetime = Field(description="Window end in UTC (excluded)")


class ExcludedReadings(BaseModel):
    duplicates: int = Field(description="Rows dropped because another row has the same instant")
    out_of_service: int = Field(description="In-window readings with docks_total = 0")


class StarvationResponse(BaseModel):
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

    station_id: int
    date: dt.date
    starved: bool = Field(description="True when empty_reading_count >= min_empty_readings")
    empty_reading_count: int = Field(
        description="Distinct in-service readings in the window with 0 bikes available"
    )
    min_empty_readings: int = Field(description="The operator's threshold")
    peak_window: PeakWindowOut
    data_status: DataStatus = Field(
        description="ok: in-service data exists; no_data: no readings; "
        "out_of_service: every reading had docks_total = 0"
    )
    readings_in_window: int = Field(description="Distinct in-service readings considered")
    excluded_readings: ExcludedReadings


class ErrorResponse(BaseModel):
    detail: str
