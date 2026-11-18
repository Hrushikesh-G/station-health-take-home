"""Tests for the authentication dependency, exercised through a minimal app.

Instead of calling the real endpoint (which also needs a database), these
tests mount ``get_current_operator`` on a tiny throwaway app with a single
``/whoami`` route that returns the operator id it resolved.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from station_health.auth import get_current_operator

# A minimal app used only by these tests.
probe = FastAPI()


@probe.get("/whoami")
def whoami(operator_id: Annotated[int, Depends(get_current_operator)]) -> dict[str, int]:
    # Reached only when authentication succeeded.
    return {"operator_id": operator_id}


def call(header: str | None):
    """Call /whoami with the given Authorization header (None = no header)."""
    headers = {} if header is None else {"Authorization": header}
    return TestClient(probe).get("/whoami", headers=headers)


# --- FR-01: authenticate with an operator bearer token ----------------------


@pytest.mark.parametrize(
    ("header", "operator_id"),
    [
        ("Bearer metro-token", 1),
        ("Bearer harbour-token", 2),
    ],
)
def test_known_tokens_resolve_to_their_operator(header: str, operator_id: int) -> None:
    # Each supplied token maps to its operator id.
    response = call(header)

    assert response.status_code == 200
    assert response.json() == {"operator_id": operator_id}


# Every way a header can be missing, malformed or wrong.
@pytest.mark.parametrize(
    "header",
    [
        None,  # no header at all
        "",  # empty header
        "Bearer",  # scheme with no token
        "Bearer ",  # scheme and space, still no token
        "Bearer unknown-token",  # token that is not in the mapping
        "Basic metro-token",  # wrong scheme
        "metro-token",  # token with no scheme
    ],
)
def test_missing_malformed_or_unknown_tokens_are_rejected(header: str | None) -> None:
    response = call(header)

    # Always the same 401 response, whatever the reason.
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}
    assert response.headers["www-authenticate"] == "Bearer"


# --- NFR-13: hardened authentication ----------------------------------------


@pytest.mark.parametrize(
    "header",
    ["bearer metro-token", "BEARER metro-token", "Bearer  metro-token", "Bearer metro-token "],
)
def test_scheme_is_case_insensitive_and_surrounding_space_is_ignored(header: str) -> None:
    # "bearer"/"BEARER" are the same scheme, and extra spaces around the
    # token are trimmed, so all of these authenticate as MetroCycle.
    assert call(header).json() == {"operator_id": 1}


@pytest.mark.parametrize("header", ["Bearer metro-token2", "Bearer metro", "Bearer METRO-TOKEN"])
def test_tokens_must_match_exactly(header: str) -> None:
    # Near misses (extra characters, a prefix, different case) are rejected:
    # the token itself is case-sensitive.
    assert call(header).status_code == 401
