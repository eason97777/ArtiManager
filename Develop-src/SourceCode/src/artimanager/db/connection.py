"""SQLite connection and initialisation utilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from artimanager.db.schema import SCHEMA_SQL


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection to the SQLite database.

    Enables WAL mode and foreign key enforcement.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str | Path) -> None:
    """Create the database file and all tables.

    Safe to call on an existing database — uses IF NOT EXISTS.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()
