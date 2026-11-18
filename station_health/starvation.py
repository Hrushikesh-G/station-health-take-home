"""The starvation rule.

Pure domain logic: no database, HTTP or framework code lives here, so the rule
can be unit tested and changed in isolation.
"""

from __future__ import annotations

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


def peak_window_for(config: OperatorConfig, day: date) -> PeakWindow:
    return PeakWindow(
        start=datetime.combine(day, config.peak_start, tzinfo=timezone.utc),
        end=datetime.combine(day, config.peak_end, tzinfo=timezone.utc),
    )
