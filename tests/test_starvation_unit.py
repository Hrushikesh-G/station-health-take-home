from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone

import pytest

from station_health.starvation import (
    DataStatus,
    OperatorConfig,
    PeakWindow,
    Reading,
    deduplicate,
    evaluate_starvation,
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


# --- FR-06: starved when the count reaches the threshold --------------------


def _empty_readings_at(*minutes_past_eight: int) -> list[Reading]:
    return [
        reading(f"2026-09-15T08:{minute:02d}:00+00:00", bikes=0, reading_id=index)
        for index, minute in enumerate(minutes_past_eight, start=1)
    ]


def test_count_equal_to_the_minimum_is_starved() -> None:
    result = evaluate_starvation(_empty_readings_at(0, 15, 30), METRO, DAY)

    assert result.empty_reading_count == 3
    assert result.starved


def test_count_one_below_the_minimum_is_not_starved() -> None:
    result = evaluate_starvation(_empty_readings_at(0, 15), METRO, DAY)

    assert result.empty_reading_count == 2
    assert not result.starved


def test_only_empty_readings_inside_the_window_are_counted() -> None:
    readings = [
        reading("2026-09-15T07:45:00+00:00", bikes=0, reading_id=1),
        reading("2026-09-15T08:00:00+00:00", bikes=5, reading_id=2),
        reading("2026-09-15T08:15:00+00:00", bikes=0, reading_id=3),
        reading("2026-09-15T10:00:00+00:00", bikes=0, reading_id=4),
    ]

    result = evaluate_starvation(readings, METRO, DAY)

    assert result.readings_in_window == 2
    assert result.empty_reading_count == 1
    assert result.window == PeakWindow(start=utc(8), end=utc(10))


# --- DQ-01: one reading per instant -----------------------------------------


def test_duplicates_are_dropped_and_counted() -> None:
    first = reading("2026-09-15T08:00:00+00:00", reading_id=1)
    second = reading("2026-09-15T08:00:00+00:00", reading_id=2)
    other = reading("2026-09-15T08:15:00+00:00", reading_id=3)

    kept, duplicates = deduplicate([first, second, other])

    assert kept == [second, other]
    assert duplicates == 1


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_highest_id_wins_regardless_of_input_order(order: tuple[int, int]) -> None:
    older = reading("2026-09-15T08:00:00+00:00", bikes=0, reading_id=7)
    newer = reading("2026-09-15T08:00:00+00:00", bikes=4, reading_id=9)
    candidates = [older, newer]

    kept, _ = deduplicate([candidates[i] for i in order])

    assert kept == [newer]


def test_duplicates_do_not_inflate_the_empty_count() -> None:
    readings = [
        reading("2026-09-15T08:00:00+00:00", bikes=0, reading_id=1),
        reading("2026-09-15T08:00:00+00:00", bikes=0, reading_id=2),
        reading("2026-09-15T08:15:00+00:00", bikes=0, reading_id=3),
    ]

    result = evaluate_starvation(readings, METRO, DAY)

    assert result.empty_reading_count == 2
    assert result.duplicates == 1
    assert not result.starved


# --- DQ-02: out-of-service readings are excluded ----------------------------


def test_out_of_service_readings_are_excluded_and_counted() -> None:
    readings = [
        reading("2026-09-15T08:00:00+00:00", bikes=0, docks=0, reading_id=1),
        reading("2026-09-15T08:15:00+00:00", bikes=0, docks=0, reading_id=2),
        reading("2026-09-15T08:30:00+00:00", bikes=0, docks=0, reading_id=3),
    ]

    result = evaluate_starvation(readings, METRO, DAY)

    assert result.empty_reading_count == 0
    assert result.readings_in_window == 0
    assert result.out_of_service == 3
    assert result.data_status is DataStatus.OUT_OF_SERVICE
    assert not result.starved


# --- DQ-03: no readings is "no data", not "healthy" -------------------------


def test_no_readings_in_the_window_is_no_data() -> None:
    result = evaluate_starvation([reading("2026-09-15T11:00:00+00:00")], METRO, DAY)

    assert result.data_status is DataStatus.NO_DATA
    assert result.readings_in_window == 0
    assert not result.starved


# --- NFR-06: data status distinguishes ok / no data / out of service --------


def test_partly_out_of_service_window_is_ok_with_exclusions_reported() -> None:
    readings = [
        reading("2026-09-15T08:00:00+00:00", bikes=0, docks=0, reading_id=1),
        reading("2026-09-15T08:15:00+00:00", bikes=0, docks=12, reading_id=2),
        reading("2026-09-15T08:30:00+00:00", bikes=3, docks=12, reading_id=3),
    ]

    result = evaluate_starvation(readings, METRO, DAY)

    assert result.data_status is DataStatus.OK
    assert result.readings_in_window == 2
    assert result.out_of_service == 1
    assert result.empty_reading_count == 1


# --- NFR-07: deterministic duplicate resolution -----------------------------


def test_same_instant_in_different_utc_notations_is_one_reading() -> None:
    zulu = reading("2026-09-15T08:00:00Z", reading_id=1)
    offset = reading("2026-09-15T08:00:00+00:00", reading_id=2)

    kept, duplicates = deduplicate([zulu, offset])

    assert kept == [offset]
    assert duplicates == 1


def test_conflicting_duplicates_are_logged(caplog: pytest.LogCaptureFixture) -> None:
    older = reading("2026-09-15T08:00:00+00:00", bikes=0, reading_id=7)
    newer = reading("2026-09-15T08:00:00+00:00", bikes=4, reading_id=9)

    with caplog.at_level(logging.WARNING, logger="station_health"):
        kept, _ = deduplicate([newer, older])

    assert kept == [newer]
    [record] = caplog.records
    assert "station 101" in record.getMessage()
    assert "rows 7 and 9" in record.getMessage()


def test_identical_duplicates_are_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    same = [reading("2026-09-15T08:00:00+00:00", reading_id=i) for i in (1, 2)]

    with caplog.at_level(logging.WARNING, logger="station_health"):
        deduplicate(same)

    assert caplog.records == []
