"""Request-scoped settings and SQLite connection handling.

Two things live here:

- ``Settings`` / ``get_settings``: where the database file is. Tests replace
  ``get_settings`` so the app reads a temporary copy instead of the real file.
- ``open_connection``: opens the database safely and always closes it.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# connect() is the supplied helper: it returns rows that can be read by column
# name (row["peak_start"]) and switches on foreign key checks.
from station_health.db import connect

# DATABASE_PATH is the supplied default: station_health.db in the project root.
from station_health.supplied import DATABASE_PATH

# Logger named "station_health.dependencies"; messages go wherever the
# application's logging is configured (uvicorn prints them to the terminal).
logger = logging.getLogger(__name__)


class DatabaseUnavailable(RuntimeError):
    """The SQLite database file does not exist (``python seed.py`` not run).

    routes.py turns this into a 503 "Database not initialised" response.
    """


# frozen=True makes Settings read-only after creation, so a request cannot
# accidentally change where another request reads from.
@dataclass(frozen=True)
class Settings:
    database_path: Path


def get_settings() -> Settings:
    """FastAPI dependency; tests override it to point at a temporary database.

    The route asks for ``Depends(get_settings)``. In production this returns the
    supplied path. In tests, ``app.dependency_overrides[get_settings]`` swaps it
    for a function returning the per-test database (see tests/conftest.py).
    """
    return Settings(database_path=DATABASE_PATH)


# @contextlib.contextmanager turns this generator into something usable with
# ``with open_connection(path) as connection:``. Code before ``yield`` runs on
# entry; the ``with`` block runs at the ``yield``; cleanup runs on exit.
@contextlib.contextmanager
def open_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection that is always closed on exit.

    ``with sqlite3.connect(...)`` only commits or rolls back; it does not close
    the connection, so ``contextlib.closing`` is used explicitly.

    Use it inside a synchronous request handler, never from a ``yield``
    dependency, so the connection is created, used and closed in one thread.

    Raises ``DatabaseUnavailable`` when the file is missing: ``sqlite3.connect``
    would otherwise create an empty database and every query would fail with
    "no such table".
    """
    # Refuse to continue if the database file has not been created. Checking
    # first also stops sqlite3 from silently creating an empty file here.
    if not Path(path).is_file():
        logger.error("Database file not found at %s; run `python seed.py`", path)
        raise DatabaseUnavailable(str(path))

    # Open the connection and hand it to the caller's ``with`` block.
    # contextlib.closing guarantees connection.close() runs when the block
    # ends, whether it finishes normally or raises (for example a 404).
    with contextlib.closing(connect(path)) as connection:
        yield connection
