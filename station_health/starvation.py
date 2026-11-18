"""The starvation rule.

Pure domain logic: no database, HTTP or framework code lives here, so the rule
can be unit tested and changed in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone


@dataclass(frozen=True)
class OperatorConfig:
    operator_id: int
    peak_start: time
    peak_end: time
    min_empty_readings: int

    @classmethod
    def from_row(
        cls,
        operator_id: int,
        peak_start: str,
        peak_end: str,
        min_empty_readings: int,
    ) -> OperatorConfig:
        return cls(
            operator_id=operator_id,
            peak_start=time.fromisoformat(peak_start),
            peak_end=time.fromisoformat(peak_end),
            min_empty_readings=min_empty_readings,
        )


@dataclass(frozen=True)
class PeakWindow:
    """A half-open UTC interval: ``start`` is included, ``end`` is excluded."""

    start: datetime
    end: datetime

    def contains(self, instant: datetime) -> bool:
        return self.start <= instant < self.end


@dataclass(frozen=True)
class Reading:
    id: int
    station_id: int
    recorded_at: str
    bikes_available: int
    docks_total: int


def peak_window_for(config: OperatorConfig, day: date) -> PeakWindow:
    return PeakWindow(
        start=datetime.combine(day, config.peak_start, tzinfo=timezone.utc),
        end=datetime.combine(day, config.peak_end, tzinfo=timezone.utc),
    )


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Values without an offset are treated as UTC, as the schema documents.
    Raises ``ValueError`` for text that is not an ISO 8601 timestamp.
    """
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def readings_in_window(readings: Iterable[Reading], window: PeakWindow) -> list[Reading]:
    """Readings whose timestamp falls in ``[window.start, window.end)``."""
    return [reading for reading in readings if window.contains(parse_utc(reading.recorded_at))]
