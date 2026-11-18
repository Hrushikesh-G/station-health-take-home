from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from httpx import Response

METRO = {"Authorization": "Bearer metro-token"}
HARBOUR = {"Authorization": "Bearer harbour-token"}
SEED_DATE = "2026-09-15"


def check(
    client: TestClient,
    station_id: int | str,
    headers: dict[str, str] | None = None,
    date: str | None = SEED_DATE,
) -> Response:
    params = {} if date is None else {"date": date}
    return client.get(f"/stations/{station_id}/starvation", params=params, headers=headers)


# --- FR-02: an operator can check one of its stations on a date -------------


def test_operator_checks_a_starved_station(client: TestClient) -> None:
    response = check(client, 101, METRO)

    assert response.status_code == 200
    assert response.json()["starved"] is True


def test_operator_checks_a_station_that_was_not_starved(client: TestClient) -> None:
    response = check(client, 102, METRO)

    assert response.status_code == 200
    assert response.json()["starved"] is False


def test_each_operator_is_evaluated_with_its_own_rule(client: TestClient) -> None:
    response = check(client, 201, HARBOUR)

    assert response.status_code == 200
    assert response.json()["starved"] is True


def test_the_endpoint_requires_authentication(client: TestClient) -> None:
    assert check(client, 101).status_code == 401


# --- FR-07: the result carries the evidence that supports it ----------------


def test_response_includes_the_supporting_count_and_the_rule_applied(
    client: TestClient,
) -> None:
    response = check(client, 101, METRO)

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

    assert body["empty_reading_count"] == 2
    assert body["min_empty_readings"] == 2
    assert body["peak_window"] == {
        "start": "2026-09-15T07:30:00Z",
        "end": "2026-09-15T09:30:00Z",
    }


def test_station_below_threshold_reports_its_count(client: TestClient) -> None:
    body = check(client, 102, METRO).json()

    assert body["starved"] is False
    assert body["empty_reading_count"] == 2
    assert body["readings_in_window"] == 4


# --- FR-08 / FR-09: tenant isolation without disclosing existence -----------


def test_another_operators_station_is_not_found(client: TestClient) -> None:
    response = check(client, 201, METRO)

    assert response.status_code == 404
    assert response.json() == {"detail": "Station not found"}


def test_isolation_holds_in_both_directions(client: TestClient) -> None:
    assert check(client, 101, HARBOUR).status_code == 404


def test_foreign_and_missing_stations_get_byte_identical_responses(
    client: TestClient,
) -> None:
    foreign = check(client, 201, METRO)
    missing = check(client, 999, METRO)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content
    assert foreign.headers.get("content-type") == missing.headers.get("content-type")
    assert foreign.headers.get("content-length") == missing.headers.get("content-length")


# --- FR-10: invalid input is rejected with 422 ------------------------------


def test_missing_date_is_rejected(client: TestClient) -> None:
    assert check(client, 101, METRO, date=None).status_code == 422


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
    assert check(client, 103, METRO).json()["data_status"] == "out_of_service"


# --- DQ-03: a day without readings is reported as "no data" -----------------


def test_day_without_readings_is_reported_as_no_data(client: TestClient) -> None:
    body = check(client, 101, METRO, date="2026-01-01").json()

    assert body["starved"] is False
    assert body["empty_reading_count"] == 0
    assert body["readings_in_window"] == 0
    assert body["data_status"] == "no_data"


def test_day_with_readings_is_reported_as_ok(client: TestClient) -> None:
    assert check(client, 102, METRO).json()["data_status"] == "ok"
