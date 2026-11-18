"""The starvation rule.

Pure domain logic: no database, HTTP or framework code lives here, so the rule
can be unit tested and changed in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from enum import Enum


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


def deduplicate(readings: Iterable[Reading]) -> tuple[list[Reading], int]:
    """Keep one reading per instant: the latest row (highest id) wins.

    Returns the kept readings and how many duplicates were dropped.
    """
    latest: dict[datetime, Reading] = {}
    duplicates = 0
    for reading in readings:
        instant = parse_utc(reading.recorded_at)
        current = latest.get(instant)
        if current is None:
            latest[instant] = reading
            continue
        duplicates += 1
        if reading.id > current.id:
            latest[instant] = reading
    return list(latest.values()), duplicates


def is_out_of_service(reading: Reading) -> bool:
    """A station with no docks cannot hold bikes, so it cannot be starved."""
    return reading.docks_total == 0


def is_empty(reading: Reading) -> bool:
    """A reading is empty when no bikes are available to start a journey."""
    return reading.bikes_available == 0


class DataStatus(str, Enum):
    """Whether the result rests on data, so "not starved" is never ambiguous."""

    OK = "ok"
    NO_DATA = "no_data"
    OUT_OF_SERVICE = "out_of_service"


@dataclass(frozen=True)
class StarvationResult:
    window: PeakWindow
    min_empty_readings: int
    empty_reading_count: int
    readings_in_window: int
    duplicates: int
    out_of_service: int
    data_status: DataStatus

    @property
    def starved(self) -> bool:
        return self.empty_reading_count >= self.min_empty_readings


def evaluate_starvation(
    readings: Iterable[Reading], config: OperatorConfig, day: date
) -> StarvationResult:
    """Apply the operator's starvation rule to one station's readings for ``day``."""
    window = peak_window_for(config, day)
    unique, duplicates = deduplicate(readings_in_window(readings, window))
    in_service = [reading for reading in unique if not is_out_of_service(reading)]
    return StarvationResult(
        window=window,
        min_empty_readings=config.min_empty_readings,
        empty_reading_count=sum(1 for reading in in_service if is_empty(reading)),
        readings_in_window=len(in_service),
        duplicates=duplicates,
        out_of_service=len(unique) - len(in_service),
        data_status=_data_status(total=len(unique), in_service=len(in_service)),
    )


def _data_status(total: int, in_service: int) -> DataStatus:
    if total == 0:
        return DataStatus.NO_DATA
    if in_service == 0:
        return DataStatus.OUT_OF_SERVICE
    return DataStatus.OK
