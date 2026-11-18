"""End-to-end tests of GET /stations/{station_id}/starvation.

Each test sends a real HTTP request through FastAPI (using the ``client``
fixture from conftest.py) against a fresh copy of the seeded database, and
checks the status code and JSON body. Sections are labelled with the
requirement ID they prove.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import Response

# Authorization headers for the two operators, and the date the seed data
# covers.
METRO = {"Authorization": "Bearer metro-token"}
HARBOUR = {"Authorization": "Bearer harbour-token"}
SEED_DATE = "2026-09-15"


def check(
    client: TestClient,
    station_id: int | str,
    headers: dict[str, str] | None = None,
    date: str | None = SEED_DATE,
) -> Response:
    """Call the starvation endpoint. ``date=None`` leaves the date out entirely."""
    params = {} if date is None else {"date": date}
    return client.get(f"/stations/{station_id}/starvation", params=params, headers=headers)


# --- FR-02: an operator can check one of its stations on a date -------------


def test_operator_checks_a_starved_station(client: TestClient) -> None:
    # Station 101 had 3 empty readings: MetroCycle's minimum.
    response = check(client, 101, METRO)

    assert response.status_code == 200
    assert response.json()["starved"] is True


def test_operator_checks_a_station_that_was_not_starved(client: TestClient) -> None:
    # Station 102 had only 2 empty readings.
    response = check(client, 102, METRO)

    assert response.status_code == 200
    assert response.json()["starved"] is False


def test_each_operator_is_evaluated_with_its_own_rule(client: TestClient) -> None:
    # Harbour's earlier window and lower threshold make station 201 starved.
    response = check(client, 201, HARBOUR)

    assert response.status_code == 200
    assert response.json()["starved"] is True


def test_the_endpoint_requires_authentication(client: TestClient) -> None:
    # No Authorization header at all.
    assert check(client, 101).status_code == 401


# --- FR-07: the result carries the evidence that supports it ----------------


def test_response_includes_the_supporting_count_and_the_rule_applied(
    client: TestClient,
) -> None:
    response = check(client, 101, METRO)

    # The complete response body, field by field.
    assert response.json() == {
        "station_id": 101,
        "date": SEED_DATE,
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


def test_harbour_result_reports_its_own_window_and_threshold(client: TestClient) -> None:
    body = check(client, 201, HARBOUR).json()

    # Harbour's rule, not MetroCycle's, appears in the response.
    assert body["empty_reading_count"] == 2
    assert body["min_empty_readings"] == 2
    assert body["peak_window"] == {
        "start": "2026-09-15T07:30:00Z",
        "end": "2026-09-15T09:30:00Z",
    }


def test_station_below_threshold_reports_its_count(client: TestClient) -> None:
    body = check(client, 102, METRO).json()

    # A "no" answer still shows the count behind it.
    assert body["starved"] is False
    assert body["empty_reading_count"] == 2
    assert body["readings_in_window"] == 4


# --- FR-08 / FR-09: tenant isolation without disclosing existence -----------


def test_another_operators_station_is_not_found(client: TestClient) -> None:
    # MetroCycle asks about Harbour's station 201.
    response = check(client, 201, METRO)

    assert response.status_code == 404
    assert response.json() == {"detail": "Station not found"}


def test_isolation_holds_in_both_directions(client: TestClient) -> None:
    # Harbour asks about MetroCycle's station 101.
    assert check(client, 101, HARBOUR).status_code == 404


def test_foreign_and_missing_stations_get_byte_identical_responses(
    client: TestClient,
) -> None:
    foreign = check(client, 201, METRO)  # exists, but belongs to Harbour
    missing = check(client, 999, METRO)  # does not exist at all

    # Status, body and headers must all match, so MetroCycle cannot tell
    # which station exists.
    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content
    assert foreign.headers.get("content-type") == missing.headers.get("content-type")
    assert foreign.headers.get("content-length") == missing.headers.get("content-length")


# --- FR-10: invalid input is rejected with 422 ------------------------------


def test_missing_date_is_rejected(client: TestClient) -> None:
    assert check(client, 101, METRO, date=None).status_code == 422


# Impossible date, missing zero, wrong order, words, empty string.
@pytest.mark.parametrize("bad_date", ["2026-02-30", "2026-9-15", "15-09-2026", "yesterday", ""])
def test_malformed_dates_are_rejected(client: TestClient, bad_date: str) -> None:
    assert check(client, 101, METRO, date=bad_date).status_code == 422


def test_non_integer_station_id_is_rejected(client: TestClient) -> None:
    assert check(client, "abc", METRO).status_code == 422


# --- DQ-01: duplicate readings do not inflate the count ---------------------


def test_duplicate_reading_is_counted_once(client: TestClient) -> None:
    body = check(client, 104, METRO).json()

    # Station 104 has two identical 08:00 rows; counting both would give 3
    # empty readings and a false "starved".
    assert body["starved"] is False
    assert body["empty_reading_count"] == 2
    assert body["readings_in_window"] == 3
    assert body["excluded_readings"]["duplicates"] == 1


# --- DQ-02: out-of-service readings are not starvation ----------------------


def test_station_with_no_docks_is_not_reported_as_starved(client: TestClient) -> None:
    body = check(client, 103, METRO).json()

    # Station 103 reports 0 bikes but also 0 docks: it is out of service.
    assert body["starved"] is False
    assert body["empty_reading_count"] == 0
    assert body["readings_in_window"] == 0
    assert body["excluded_readings"]["out_of_service"] == 3


def test_station_out_of_service_all_window_is_flagged(client: TestClient) -> None:
    # Every reading was out of service, and the status says so explicitly.
    assert check(client, 103, METRO).json()["data_status"] == "out_of_service"


# --- DQ-03: a day without readings is reported as "no data" -----------------


def test_day_without_readings_is_reported_as_no_data(client: TestClient) -> None:
    # The seed data has nothing on 2026-01-01.
    body = check(client, 101, METRO, date="2026-01-01").json()

    assert body["starved"] is False
    assert body["empty_reading_count"] == 0
    assert body["readings_in_window"] == 0
    assert body["data_status"] == "no_data"


def test_day_with_readings_is_reported_as_ok(client: TestClient) -> None:
    assert check(client, 102, METRO).json()["data_status"] == "ok"


# --- NFR-01: every seeded station gives the expected result -----------------
# Mirrors section 4.2 of the functional design. Four of the six stations
# contain a trap that a naive count gets wrong.

SEED_EXPECTATIONS = [
    # station, headers, starved, empty, in window, duplicates, out of service, status
    (101, METRO, True, 3, 5, 0, 0, "ok"),  # 07:45, 10:00 and 2026-09-14 excluded
    (102, METRO, False, 2, 4, 0, 0, "ok"),  # baseline
    (103, METRO, False, 0, 0, 0, 3, "out_of_service"),  # docks_total = 0
    (104, METRO, False, 2, 3, 1, 0, "ok"),  # duplicate 08:00 row
    (201, HARBOUR, True, 2, 3, 0, 0, "ok"),  # Harbour's own window and threshold
    (202, HARBOUR, False, 1, 2, 0, 0, "ok"),  # one below Harbour's threshold
]


# One test run per row above; "ids" names each run after its station number
# so a failure reads as, for example, "test_seed_data_...[104]".
@pytest.mark.parametrize(
    "station_id,headers,starved,empty,in_window,duplicates,out_of_service,status",
    SEED_EXPECTATIONS,
    ids=[str(row[0]) for row in SEED_EXPECTATIONS],
)
def test_seed_data_produces_the_expected_result(
    client: TestClient,
    station_id: int,
    headers: dict[str, str],
    starved: bool,
    empty: int,
    in_window: int,
    duplicates: int,
    out_of_service: int,
    status: str,
) -> None:
    response = check(client, station_id, headers)

    assert response.status_code == 200
    body = response.json()
    assert body["starved"] is starved
    assert body["empty_reading_count"] == empty
    assert body["readings_in_window"] == in_window
    assert body["excluded_readings"] == {
        "duplicates": duplicates,
        "out_of_service": out_of_service,
    }
    assert body["data_status"] == status


def test_previous_day_is_evaluated_on_its_own_readings(client: TestClient) -> None:
    # On 2026-09-14, station 101 has just one empty reading (08:15).
    body = check(client, 101, METRO, date="2026-09-14").json()

    assert body["starved"] is False
    assert body["empty_reading_count"] == 1
