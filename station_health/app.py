"""Application entry point.

``uvicorn station_health.app:app`` imports this module and serves the ``app``
object defined below. Everything the service exposes is registered here.
"""

# Lets type hints refer to names that are defined later (standard modern Python).
from __future__ import annotations

from fastapi import FastAPI

# The router holds the starvation endpoint; it is defined in routes.py.
from station_health.routes import router


# Create the web application. The title is shown at the top of /docs.
app = FastAPI(title="Station Health")

# Attach every route from routes.py (GET /stations/{station_id}/starvation).
app.include_router(router)


# Supplied health check: GET /health returns {"status": "ok"} so a load
# balancer or a person can confirm the process is up. It needs no token.
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
