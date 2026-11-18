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
    assert response.json() == {"station_id": 101, "date": SEED_DATE, "starved": True}


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
