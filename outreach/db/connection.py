"""SQLite connection helper."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from outreach.config import DB_PATH


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with foreign keys on and dict-style rows."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
