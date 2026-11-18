from __future__ import annotations

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
        "readings_in_window": 5,
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
