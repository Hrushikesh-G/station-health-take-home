"""API-level tests for the gap-closure requirements (NFR-06 to NFR-15).

These go beyond the brief's happy path: corrupt data, broken configuration,
hostile input, concurrent load, a missing database, authentication edge
cases, API documentation and logging. Where a test needs bad data it changes
only its own temporary database (never seed.py).
"""

from __future__ import annotations

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from station_health.app import app
from station_health.dependencies import Settings, get_settings

METRO = {"Authorization": "Bearer metro-token"}
SEED_DATE = "2026-09-15"


def starvation(client: TestClient, station_id: int = 101, date: str = SEED_DATE) -> dict:
    """Call the endpoint as MetroCycle, require a 200 and return the JSON body."""
    response = client.get(
        f"/stations/{station_id}/starvation", params={"date": date}, headers=METRO
    )
    # On failure, pytest shows the response text to explain why.
    assert response.status_code == 200, response.text
    return response.json()


def execute(database_path: Path, sql: str, params: tuple = ()) -> None:
    """Change the per-test temporary database only; seed.py is never touched."""
    # "with connection" commits the change; close() then releases the file.
    with sqlite3.connect(database_path) as connection:
        connection.execute(sql, params)
    connection.close()


# --- NFR-08: an unparseable timestamp never breaks a request ----------------


def test_unparseable_reading_is_skipped_and_logged(
    client: TestClient, database_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Record the normal answer first.
    baseline = starvation(client)

    # Add a corrupt row. It sorts inside the SQL range, so it is fetched,
    # but hour 25 is invalid.
    execute(
        database_path,
        "INSERT INTO dock_readings (station_id, recorded_at, bikes_available, docks_total) "
        "VALUES (101, '2026-09-15T25:00:00+00:00', 0, 12)",
    )

    # The answer is unchanged (no 500) and the bad row is reported in the log.
    with caplog.at_level(logging.WARNING, logger="station_health"):
        assert starvation(client) == baseline

    assert any("unparseable recorded_at" in r.getMessage() for r in caplog.records)


# --- NFR-09: invalid operator configuration fails loudly --------------------


# Three ways to break MetroCycle's configuration.
@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE operator_configs SET peak_end = peak_start WHERE operator_id = 1",  # empty window
        "UPDATE operator_configs SET peak_start = 'eight' WHERE operator_id = 1",  # not a time
        "DELETE FROM operator_configs WHERE operator_id = 1",  # no config at all
    ],
)
def test_invalid_operator_config_returns_500_and_is_logged(
    client: TestClient, database_path: Path, caplog: pytest.LogCaptureFixture, sql: str
) -> None:
    execute(database_path, sql)

    with caplog.at_level(logging.ERROR, logger="station_health"):
        response = client.get(
            "/stations/101/starvation", params={"date": SEED_DATE}, headers=METRO
        )

    # A generic message for the caller; the detail goes to the log.
    assert response.status_code == 500
    assert response.json() == {"detail": "Operator configuration invalid"}
    assert any("operator 1" in r.getMessage() for r in caplog.records)


# --- NFR-10: strict input validation ----------------------------------------


def status_for(client: TestClient, station_id: object = 101, date: str = SEED_DATE) -> int:
    """Call the endpoint as MetroCycle and return just the status code."""
    return client.get(
        f"/stations/{station_id}/starvation", params={"date": date}, headers=METRO
    ).status_code


# Inputs that FastAPI's default date parsing would accept as a date.
@pytest.mark.parametrize(
    "lenient_date",
    ["1694736000", "2026-09-15T00:00:00", "2026-09-15 08:00", "+2026-09-15"],
)
def test_dates_that_default_coercion_would_accept_are_rejected(
    client: TestClient, lenient_date: str
) -> None:
    # FastAPI's date type turns "1694736000" into 2023-09-15 without error.
    assert status_for(client, date=lenient_date) == 422


# Zero, negative, and too large for SQLite's 64-bit integers.
@pytest.mark.parametrize("station_id", ["0", "-5", "99999999999999999999"])
def test_out_of_range_station_ids_are_rejected_not_500(
    client: TestClient, station_id: str
) -> None:
    assert status_for(client, station_id=station_id) == 422


@pytest.mark.parametrize("date", ["0001-01-01", "9999-12-31"])
def test_dates_outside_the_supported_range_are_rejected(client: TestClient, date: str) -> None:
    # The first and last representable dates would overflow the window maths.
    response = client.get("/stations/101/starvation", params={"date": date}, headers=METRO)

    assert response.status_code == 422
    assert response.json() == {"detail": "date must be between 0001-01-02 and 9999-12-28"}


@pytest.mark.parametrize("date", ["0001-01-02", "9999-12-28"])
def test_supported_range_edges_are_accepted(client: TestClient, date: str) -> None:
    # The extreme dates that are allowed work, and simply have no data.
    assert starvation(client, date=date)["data_status"] == "no_data"


# --- NFR-11: connections never cross threads --------------------------------


def test_concurrent_requests_all_succeed_with_identical_results(client: TestClient) -> None:
    # With a connection handed out by a yield dependency, 196 of 200 such
    # requests failed with cross-thread SQLite errors.
    def fetch(_: int) -> tuple[int, bytes]:
        response = client.get(
            "/stations/101/starvation", params={"date": SEED_DATE}, headers=METRO
        )
        return response.status_code, response.content

    # Send 200 requests from 16 threads at once.
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(fetch, range(200)))

    # Every request succeeded, and every body is identical.
    assert {status for status, _ in results} == {200}
    assert len({body for _, body in results}) == 1


# --- NFR-12: a missing database is reported, never created ------------------


def test_missing_database_returns_503_and_creates_no_file(
    client: TestClient, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Point the app at a database file that does not exist. (The client
    # fixture removes this override again after the test.)
    missing = tmp_path / "not-seeded.db"
    app.dependency_overrides[get_settings] = lambda: Settings(database_path=missing)

    with caplog.at_level(logging.ERROR, logger="station_health"):
        response = client.get(
            "/stations/101/starvation", params={"date": SEED_DATE}, headers=METRO
        )

    # A clear 503, no empty file left behind, and a hint in the log.
    assert response.status_code == 503
    assert response.json() == {"detail": "Database not initialised"}
    assert not missing.exists()
    assert any("run `python seed.py`" in r.getMessage() for r in caplog.records)


# --- NFR-13: every authentication failure looks the same --------------------


def test_all_authentication_failures_get_an_identical_response(client: TestClient) -> None:
    headers = [
        {},  # no header
        {"Authorization": "Bearer unknown-token"},  # unknown token
        {"Authorization": "Basic metro-token"},  # wrong scheme
        {"Authorization": "Bearer "},  # empty token
    ]
    responses = [
        client.get("/stations/101/starvation", params={"date": SEED_DATE}, headers=h)
        for h in headers
    ]

    # All four are 401 with the same body and header, so the reason is hidden.
    assert {r.status_code for r in responses} == {401}
    assert len({r.content for r in responses}) == 1
    assert {r.headers["www-authenticate"] for r in responses} == {"Bearer"}


def test_lower_case_scheme_is_accepted_end_to_end(client: TestClient) -> None:
    response = client.get(
        "/stations/101/starvation",
        params={"date": SEED_DATE},
        headers={"Authorization": "bearer metro-token"},
    )

    assert response.status_code == 200


def test_authentication_runs_before_input_validation(client: TestClient) -> None:
    # Both the station id and the date are invalid AND there is no token.
    # The answer is 401, so an unauthenticated caller learns nothing about
    # what input the API expects.
    response = client.get(
        "/stations/abc/starvation", params={"date": "not-a-date"}, headers={}
    )

    assert response.status_code == 401


# --- NFR-14: the API contract is documented in OpenAPI ----------------------


def test_openapi_documents_the_endpoint_and_its_errors(client: TestClient) -> None:
    # /openapi.json is the machine-readable description that /docs is built from.
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/stations/{station_id}/starvation"]["get"]

    # Every status code the endpoint can return is documented.
    assert set(operation["responses"]) == {"200", "401", "404", "422", "500", "503"}
    # The 200 body is described by the StarvationResponse model.
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/StarvationResponse"
    }
    # The endpoint declares Bearer authentication (this is what makes /docs
    # show the Authorize button).
    assert operation["security"] == [{"OperatorToken": []}]
    assert schema["components"]["securitySchemes"]["OperatorToken"]["scheme"] == "bearer"
    # The allowed data_status values are listed.
    data_status = schema["components"]["schemas"]["DataStatus"]
    assert data_status["enum"] == ["ok", "no_data", "out_of_service"]


# --- NFR-15: logs carry context but never secrets ---------------------------


def test_tokens_never_appear_in_any_log_record(
    client: TestClient, database_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Trigger every warning and error path alongside good and bad credentials:
    # a corrupt timestamp, plus a second 08:15 row that conflicts with the
    # seeded one (6 bikes vs 0 bikes).
    execute(
        database_path,
        "INSERT INTO dock_readings (station_id, recorded_at, bikes_available, docks_total) "
        "VALUES (101, '2026-09-15T25:00:00+00:00', 0, 12), "
        "(101, '2026-09-15T08:15:00+00:00', 6, 12)",
    )
    requests = [
        {"Authorization": "Bearer metro-token"},
        {"Authorization": "Bearer harbour-token"},
        {"Authorization": "Bearer guessed-secret-token"},
        {"Authorization": "Basic metro-token"},
    ]

    # Capture every log message from every logger, at every level.
    with caplog.at_level(logging.DEBUG):
        for headers in requests:
            client.get("/stations/101/starvation", params={"date": SEED_DATE}, headers=headers)
        # Finally break the config to trigger the error path too.
        execute(database_path, "DELETE FROM operator_configs WHERE operator_id = 1")
        client.get("/stations/101/starvation", params={"date": SEED_DATE}, headers=METRO)

    logged = "\n".join(record.getMessage() for record in caplog.records)

    # Each problem was logged...
    assert "unparseable recorded_at" in logged
    assert "Conflicting duplicate readings" in logged
    assert "Cannot evaluate starvation" in logged
    # ...but no token, valid or guessed, appears anywhere in the logs.
    for secret in ("metro-token", "harbour-token", "guessed-secret-token"):
        assert secret not in logged


def test_service_logs_share_one_namespace(
    client: TestClient, database_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    execute(database_path, "DELETE FROM operator_configs WHERE operator_id = 1")

    with caplog.at_level(logging.DEBUG):
        client.get("/stations/101/starvation", params={"date": SEED_DATE}, headers=METRO)

    # Every warning or error comes from a "station_health.*" logger, so an
    # operator can route all of the service's logs with one setting.
    service_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert service_records
    assert all(r.name.startswith("station_health.") for r in service_records)
