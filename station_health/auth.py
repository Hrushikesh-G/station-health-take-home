"""Bearer token authentication against the supplied token mapping."""

from __future__ import annotations

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
    """Return the operator id for ``Authorization: Bearer <token>`` or raise 401."""
    prefix = "Bearer "
    if authorization is None or not authorization.startswith(prefix):
        raise _unauthenticated()

    operator_id = TOKENS.get(authorization[len(prefix):])
    if operator_id is None:
        raise _unauthenticated()
    return operator_id
