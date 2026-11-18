"""Response models for the HTTP API."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class StarvationResponse(BaseModel):
    station_id: int
    date: dt.date
    starved: bool
