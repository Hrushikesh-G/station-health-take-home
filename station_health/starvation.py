"""The starvation rule.

Pure domain logic: no database, HTTP or framework code lives here, so the rule
can be unit tested and changed in isolation.

The rule, in plain words: a station is *starved* on a date when, inside its
operator's morning peak window (UTC, start included, end excluded), it has at
least the operator's minimum number of readings with zero bikes available.

``evaluate_starvation`` at the bottom of this file applies the rule in steps:

1. build the window for the date        -> ``peak_window_for``
2. keep readings inside the window      -> ``readings_in_window``
3. drop duplicate readings              -> ``deduplicate``
4. drop out-of-service readings         -> ``is_out_of_service``
5. count empty readings                 -> ``is_empty``
6. compare the count with the minimum   -> ``StarvationResult.starved``
7. say whether the answer rests on data -> ``DataStatus``
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum

# Logger named "station_health.starvation" for data problems worth a warning.
logger = logging.getLogger(__name__)


class InvalidOperatorConfig(ValueError):
    """The operator's stored configuration cannot be used to evaluate the rule."""


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


# @dataclass generates __init__, __eq__ and __repr__ from the fields below.
# frozen=True makes instances read-only, so a config cannot change mid-request.
@dataclass(frozen=True)
class OperatorConfig:
    """One operator's rule, e.g. MetroCycle: 08:00 to 10:00 UTC, at least 3."""

    operator_id: int
    peak_start: time  # window start, UTC, included
    peak_end: time  # window end, UTC, excluded
    min_empty_readings: int  # empty readings needed to count as starved

    @classmethod
    def from_row(
        cls,
        operator_id: int,
        peak_start: str,
        peak_end: str,
        min_empty_readings: int,
    ) -> OperatorConfig:
        """Build a validated config from stored values.

        Raises ``InvalidOperatorConfig`` rather than letting a bad row
        produce a silently wrong answer.
        """
        # Parse "08:00" style text into time objects. Anything that is not a
        # valid time (for example "8am" or "") is rejected.
        try:
            start = time.fromisoformat(peak_start)
            end = time.fromisoformat(peak_end)
        except (TypeError, ValueError) as exc:
            raise InvalidOperatorConfig(
                f"operator {operator_id}: peak times must be HH:MM, "
                f"got {peak_start!r} and {peak_end!r}"
            ) from exc

        # Peak times are defined in UTC; a value such as "08:00+01:00" would
        # be ambiguous, so it is rejected.
        if start.tzinfo is not None or end.tzinfo is not None:
            raise InvalidOperatorConfig(
                f"operator {operator_id}: peak times are UTC and must not carry an offset"
            )

        # Equal start and end would be a window of zero length.
        if start == end:
            raise InvalidOperatorConfig(
                f"operator {operator_id}: peak window {peak_start} to {peak_end} is empty"
            )

        # The threshold must be a whole number of at least 1.
        if not isinstance(min_empty_readings, int) or min_empty_readings < 1:
            raise InvalidOperatorConfig(
                f"operator {operator_id}: min_empty_readings must be a positive integer, "
                f"got {min_empty_readings!r}"
            )

        # All checks passed: create the config.
        return cls(operator_id, start, end, min_empty_readings)


@dataclass(frozen=True)
class PeakWindow:
    """A half-open UTC interval: ``start`` is included, ``end`` is excluded.

    ``end`` falls on the next day when the operator's window crosses midnight.
    """

    start: datetime
    end: datetime

    def contains(self, instant: datetime) -> bool:
        # "<=" on the left includes the start; "<" on the right excludes the
        # end. A reading at exactly 10:00 is therefore outside 08:00-10:00.
        return self.start <= instant < self.end


@dataclass(frozen=True)
class Reading:
    """One row of dock_readings: a station's state at one moment."""

    id: int  # row id; higher means inserted later
    station_id: int
    recorded_at: str  # ISO 8601 text, parsed by parse_utc when needed
    bikes_available: int
    docks_total: int  # 0 means the station is out of service


# ---------------------------------------------------------------------------
# Step 1: the window
# ---------------------------------------------------------------------------


def peak_window_for(config: OperatorConfig, day: date) -> PeakWindow:
    """The operator's window that starts on ``day`` (UTC)."""
    # Combine the date with the configured times, e.g. 2026-09-15 + 08:00
    # gives 2026-09-15 08:00 UTC.
    start = datetime.combine(day, config.peak_start, tzinfo=timezone.utc)
    end = datetime.combine(day, config.peak_end, tzinfo=timezone.utc)

    # A window such as 23:00 to 01:00 ends before it starts on the same date,
    # so it must cross midnight: move the end to the next day.
    if end <= start:
        end += timedelta(days=1)
    return PeakWindow(start=start, end=end)


# ---------------------------------------------------------------------------
# Step 2: readings inside the window
# ---------------------------------------------------------------------------


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Values without an offset are treated as UTC, as the schema documents.
    Raises ``ValueError`` for text that is not an ISO 8601 timestamp.
    """
    # Accepts forms such as "2026-09-15T08:15:00+00:00", "...Z" and
    # "...+05:30".
    parsed = datetime.fromisoformat(value)

    # No offset given ("2026-09-15T08:15:00"): label it as UTC.
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    # Offset given: convert to UTC, so 13:45+05:30 becomes 08:15 UTC.
    return parsed.astimezone(timezone.utc)


def readings_in_window(readings: Iterable[Reading], window: PeakWindow) -> list[Reading]:
    """Readings whose timestamp falls in ``[window.start, window.end)``.

    A reading whose timestamp cannot be parsed is skipped and logged rather
    than failing the whole request.
    """
    selected = []
    for reading in readings:
        # Turn the stored text into a real UTC moment.
        try:
            instant = parse_utc(reading.recorded_at)
        except (TypeError, ValueError):
            # Corrupt timestamp (e.g. hour 25): skip this one row, record
            # which row it was so someone can fix the data, and carry on.
            logger.warning(
                "Skipping reading %s for station %s: unparseable recorded_at %r",
                reading.id,
                reading.station_id,
                reading.recorded_at,
            )
            continue

        # Keep the reading only if it falls inside the half-open window.
        if window.contains(instant):
            selected.append(reading)
    return selected


# ---------------------------------------------------------------------------
# Step 3: duplicates
# ---------------------------------------------------------------------------


def deduplicate(readings: Iterable[Reading]) -> tuple[list[Reading], int]:
    """Keep one reading per instant: the latest row (highest id) wins.

    Instants are compared after conversion to UTC, so ``08:00:00Z`` and
    ``08:00:00+00:00`` are the same reading. Duplicates that disagree are
    logged. Returns the kept readings and how many duplicates were dropped.
    """
    # Map each moment in time to the reading kept for it.
    latest: dict[datetime, Reading] = {}
    duplicates = 0

    for reading in readings:
        instant = parse_utc(reading.recorded_at)
        current = latest.get(instant)

        # First reading seen for this moment: keep it and move on.
        if current is None:
            latest[instant] = reading
            continue

        # Another reading already exists for this moment: it is a duplicate.
        duplicates += 1

        # If the two rows disagree (different bikes or docks), the data is
        # suspicious; log both row ids so it can be investigated.
        if _values(reading) != _values(current):
            logger.warning(
                "Conflicting duplicate readings for station %s at %s (rows %s and %s); "
                "keeping the highest id",
                reading.station_id,
                instant.isoformat(),
                min(reading.id, current.id),
                max(reading.id, current.id),
            )

        # Keep whichever row was inserted last (highest id), regardless of
        # the order the rows arrived in, so the result is always the same.
        if reading.id > current.id:
            latest[instant] = reading

    return list(latest.values()), duplicates


def _values(reading: Reading) -> tuple[int, int]:
    """The measured values of a reading, used to spot conflicting duplicates."""
    return reading.bikes_available, reading.docks_total


# ---------------------------------------------------------------------------
# Steps 4 and 5: what counts
# ---------------------------------------------------------------------------


def is_out_of_service(reading: Reading) -> bool:
    """A station with no docks cannot hold bikes, so it cannot be starved."""
    return reading.docks_total == 0


def is_empty(reading: Reading) -> bool:
    """A reading is empty when no bikes are available to start a journey."""
    return reading.bikes_available == 0


# ---------------------------------------------------------------------------
# Steps 6 and 7: the result
# ---------------------------------------------------------------------------


# Inheriting from str makes each member serialise as its text value
# ("ok", "no_data", "out_of_service") in the JSON response.
class DataStatus(str, Enum):
    """Whether the result rests on data, so "not starved" is never ambiguous."""

    OK = "ok"  # at least one in-service reading in the window
    NO_DATA = "no_data"  # no readings in the window at all
    OUT_OF_SERVICE = "out_of_service"  # readings exist, all with docks_total = 0


@dataclass(frozen=True)
class StarvationResult:
    """Everything the rule worked out, including the evidence for the answer."""

    window: PeakWindow  # the UTC window that was applied
    min_empty_readings: int  # the operator's threshold
    empty_reading_count: int  # in-service readings with 0 bikes
    readings_in_window: int  # in-service readings considered
    duplicates: int  # rows dropped as duplicates
    out_of_service: int  # readings dropped because docks_total was 0
    data_status: DataStatus

    # A property is computed on access, so "starved" can never disagree with
    # the count and threshold it is based on.
    @property
    def starved(self) -> bool:
        return self.empty_reading_count >= self.min_empty_readings


def evaluate_starvation(
    readings: Iterable[Reading], config: OperatorConfig, day: date
) -> StarvationResult:
    """Apply the operator's starvation rule to one station's readings for ``day``."""
    # Step 1: the operator's window on the requested date.
    window = peak_window_for(config, day)

    # Steps 2 and 3: readings inside the window, one per moment.
    unique, duplicates = deduplicate(readings_in_window(readings, window))

    # Step 4: keep only readings taken while the station was in service.
    in_service = [reading for reading in unique if not is_out_of_service(reading)]

    # Steps 5 to 7: count, compare (via .starved) and label the result.
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
    """Label the result: no readings, only out-of-service readings, or ok."""
    if total == 0:
        return DataStatus.NO_DATA
    if in_service == 0:
        return DataStatus.OUT_OF_SERVICE
    return DataStatus.OK
