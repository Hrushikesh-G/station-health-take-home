from __future__ import annotations

import pytest
from fastapi import HTTPException

from station_health.auth import get_current_operator


@pytest.mark.parametrize(
    ("header", "operator_id"),
    [
        ("Bearer metro-token", 1),
        ("Bearer harbour-token", 2),
    ],
)
def test_known_tokens_resolve_to_their_operator(header: str, operator_id: int) -> None:
    assert get_current_operator(header) == operator_id


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer",
        "Bearer ",
        "Bearer unknown-token",
        "Basic metro-token",
        "metro-token",
    ],
)
def test_missing_malformed_or_unknown_tokens_are_rejected(header: str | None) -> None:
    with pytest.raises(HTTPException) as raised:
        get_current_operator(header)

    assert raised.value.status_code == 401
    assert raised.value.detail == "Not authenticated"
    assert raised.value.headers == {"WWW-Authenticate": "Bearer"}


# --- NFR-13: hardened authentication ----------------------------------------


@pytest.mark.parametrize(
    "header",
    ["bearer metro-token", "BEARER metro-token", "Bearer  metro-token", "Bearer metro-token "],
)
def test_scheme_is_case_insensitive_and_surrounding_space_is_ignored(header: str) -> None:
    assert get_current_operator(header) == 1


@pytest.mark.parametrize("header", ["Bearer metro-token2", "Bearer metro", "Bearer METRO-TOKEN"])
def test_tokens_must_match_exactly(header: str) -> None:
    with pytest.raises(HTTPException):
        get_current_operator(header)
