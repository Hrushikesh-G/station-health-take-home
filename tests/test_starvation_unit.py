from __future__ import annotations

from datetime import date, datetime, time, timezone

from station_health.starvation import (
    OperatorConfig,
    PeakWindow,
    Reading,
    is_empty,
    parse_utc,
    peak_window_for,
    readings_in_window,
)

UTC = timezone.utc
DAY = date(2026, 9, 15)
METRO = OperatorConfig(operator_id=1, peak_start=time(8), peak_end=time(10), min_empty_readings=3)


def utc(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def reading(
    recorded_at: str, bikes: int = 0, docks: int = 12, reading_id: int = 1
) -> Reading:
    return Reading(
        id=reading_id,
        station_id=101,
        recorded_at=recorded_at,
        bikes_available=bikes,
        docks_total=docks,
    )


# --- FR-03: the operator's own window and threshold -------------------------


def test_config_from_row_parses_peak_times() -> None:
    config = OperatorConfig.from_row(2, "07:30", "09:30", 2)

    assert config == OperatorConfig(2, time(7, 30), time(9, 30), 2)


def test_peak_window_is_built_in_utc_on_the_requested_date() -> None:
    assert peak_window_for(METRO, DAY) == PeakWindow(start=utc(8), end=utc(10))


# --- FR-04: half-open window on the requested date --------------------------


def test_window_includes_its_start_and_excludes_its_end() -> None:
    window = peak_window_for(METRO, DAY)
    at_start = reading("2026-09-15T08:00:00+00:00", reading_id=1)
    at_end = reading("2026-09-15T10:00:00+00:00", reading_id=2)

    assert readings_in_window([at_start, at_end], window) == [at_start]


def test_readings_just_outside_the_window_or_on_other_dates_are_ignored() -> None:
    window = peak_window_for(METRO, DAY)
    candidates = [
        reading("2026-09-15T07:59:59+00:00"),
        reading("2026-09-15T09:59:59+00:00"),
        reading("2026-09-14T08:15:00+00:00"),
        reading("2026-09-16T08:15:00+00:00"),
    ]

    assert readings_in_window(candidates, window) == [candidates[1]]


def test_parse_utc_returns_aware_utc_datetimes() -> None:
    assert parse_utc("2026-09-15T08:15:00+00:00") == utc(8, 15)


# --- FR-05: an empty reading has zero bikes ---------------------------------


def test_a_reading_with_zero_bikes_is_empty() -> None:
    assert is_empty(reading("2026-09-15T08:00:00+00:00", bikes=0))


def test_a_reading_with_any_bikes_is_not_empty() -> None:
    assert not is_empty(reading("2026-09-15T08:00:00+00:00", bikes=1))
