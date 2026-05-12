"""Incremental schema migrations for existing databases.

Each migration adds columns that were absent in earlier versions.
Safe to call on every startup — already-present columns are silently skipped.
"""

from __future__ import annotations

from outreach.db.connection import get_connection


def run() -> None:
    """Apply any pending migrations. Idempotent and safe to call repeatedly."""
    conn = get_connection()
    try:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        pending = [
            ("redraft_instruction", "TEXT"),
            ("redraft_requested_at", "TEXT"),
        ]
        for col, definition in pending:
            if col not in existing:
                conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {definition}")
        conn.commit()
    finally:
        conn.close()
