"""Bearer token authentication against the supplied token mapping.

Every request to the starvation endpoint must carry a header such as::

    Authorization: Bearer metro-token

This module turns that header into an operator id (1 for MetroCycle, 2 for
Harbour Bikes) or rejects the request with 401 Unauthorized.
"""

from __future__ import annotations

# hmac.compare_digest compares two values in constant time (see _operator_for).
import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# TOKENS is the supplied mapping {"metro-token": 1, "harbour-token": 2}.
from station_health.supplied import TOKENS

# HTTPBearer reads the Authorization header and splits it into a scheme
# ("Bearer") and the credentials (the token).
#
# - It also declares the Bearer scheme in the OpenAPI document, which makes
#   /docs show an "Authorize" button. Without it, Swagger UI ignores header
#   parameters named Authorization, so the endpoint could not be tried there.
# - auto_error=False means it returns None instead of raising FastAPI's
#   default 403, so every failure ends at the single 401 defined below.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="OperatorToken",
    description="Operator token from the supplied mapping, e.g. `metro-token`.",
)


def _unauthenticated() -> HTTPException:
    """Build the one and only authentication failure response.

    Returning the same status, body and header for every kind of failure
    (missing header, wrong scheme, unknown token) tells a caller nothing about
    why it was rejected. WWW-Authenticate: Bearer is the standard hint that
    the client should send a Bearer token.
    """
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_operator(
    # FastAPI calls bearer_scheme first and passes its result in here:
    # HTTPAuthorizationCredentials when the header says "Bearer <something>",
    # or None when the header is missing or uses another scheme.
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> int:
    """Return the operator id for ``Authorization: Bearer <token>`` or raise 401.

    Used as a FastAPI dependency: the route declares
    ``operator_id: Annotated[int, Depends(get_current_operator)]`` and FastAPI
    runs this function before the route body.

    The scheme is matched case-insensitively (RFC 7235), tokens are compared in
    constant time, and every failure produces the same response, so a caller
    learns nothing about why it was rejected. The header is never logged.
    """
    # Take the token text, trimming stray spaces ("Bearer  metro-token").
    # No credentials at all becomes an empty string, which never matches.
    token = credentials.credentials.strip() if credentials else ""

    # Find which operator owns this token, if any.
    operator_id = _operator_for(token)

    # Unknown, empty or missing token: reject with the shared 401.
    if operator_id is None:
        raise _unauthenticated()
    return operator_id


def _operator_for(candidate: str) -> int | None:
    """Look a token up without leaking, through timing, how much of it matched.

    A normal ``==`` or dict lookup can return faster when the first characters
    differ, which in theory lets an attacker guess a token one character at a
    time by measuring response times. ``hmac.compare_digest`` takes the same
    time however much matches, and the loop always checks every known token.
    """
    # An empty token can never be valid; skip the comparisons.
    if not candidate:
        return None

    # compare_digest works on bytes, so encode the presented token once.
    presented = candidate.encode()

    # Check the presented token against every known token. The loop does not
    # stop early on a match, so the time taken does not reveal which matched.
    matched = None
    for token, operator_id in TOKENS.items():
        if hmac.compare_digest(token.encode(), presented):
            matched = operator_id
    return matched
