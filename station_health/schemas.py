"""Response models for the HTTP API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class PeakWindowOut(BaseModel):
    start: dt.datetime
    end: dt.datetime


class ExcludedReadings(BaseModel):
    duplicates: int


class StarvationResponse(BaseModel):
    station_id: int
    date: dt.date
    starved: bool
    empty_reading_count: int
    min_empty_readings: int
    peak_window: PeakWindowOut
    readings_in_window: int
    excluded_readings: ExcludedReadings
