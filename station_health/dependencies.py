"""Request-scoped settings and SQLite connection handling."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from station_health.db import connect
from station_health.supplied import DATABASE_PATH


@dataclass(frozen=True)
class Settings:
    database_path: Path


def get_settings() -> Settings:
    """FastAPI dependency; tests override it to point at a temporary database."""
    return Settings(database_path=DATABASE_PATH)


@contextlib.contextmanager
def open_connection(path: Path) -> Iterator[sqlite3.Connection]:
    """Yield a connection that is always closed on exit.

    ``with sqlite3.connect(...)`` only commits or rolls back; it does not close
    the connection, so ``contextlib.closing`` is used explicitly.
    """
    with contextlib.closing(connect(path)) as connection:
        yield connection
