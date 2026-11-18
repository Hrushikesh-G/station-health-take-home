from __future__ import annotations

from datetime import date, datetime, time, timezone

from station_health.starvation import OperatorConfig, PeakWindow, peak_window_for

UTC = timezone.utc
DAY = date(2026, 9, 15)
METRO = OperatorConfig(operator_id=1, peak_start=time(8), peak_end=time(10), min_empty_readings=3)


def utc(hour: int, minute: int = 0, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


# --- FR-03: the operator's own window and threshold -------------------------


def test_config_from_row_parses_peak_times() -> None:
    config = OperatorConfig.from_row(2, "07:30", "09:30", 2)

    assert config == OperatorConfig(2, time(7, 30), time(9, 30), 2)


def test_peak_window_is_built_in_utc_on_the_requested_date() -> None:
    assert peak_window_for(METRO, DAY) == PeakWindow(start=utc(8), end=utc(10))
