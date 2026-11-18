"""Bearer token authentication against the supplied token mapping."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from station_health.supplied import TOKENS


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_operator(
    authorization: Annotated[str | None, Header()] = None,
) -> int:
    """Return the operator id for ``Authorization: Bearer <token>`` or raise 401.

    The scheme is matched case-insensitively (RFC 7235), tokens are compared in
    constant time, and every failure produces the same response, so a caller
    learns nothing about why it was rejected. The header is never logged.
    """
    scheme, _, token = (authorization or "").partition(" ")
    operator_id = _operator_for(token.strip()) if scheme.lower() == "bearer" else None
    if operator_id is None:
        raise _unauthenticated()
    return operator_id


def _operator_for(candidate: str) -> int | None:
    """Look a token up without leaking, through timing, how much of it matched."""
    if not candidate:
        return None
    presented = candidate.encode()
    matched = None
    for token, operator_id in TOKENS.items():
        if hmac.compare_digest(token.encode(), presented):
            matched = operator_id
    return matched
