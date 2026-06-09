"""Incremental schema + data migrations for existing databases.

Each migration is idempotent — safe to call on every startup. Already-present
columns and already-migrated rows are silently skipped.
"""

from __future__ import annotations

import json

from outreach.db.connection import get_connection


def run() -> None:
    """Apply any pending migrations. Idempotent and safe to call repeatedly."""
    conn = get_connection()
    try:
        _add_redraft_columns(conn)
        _add_auto_reply_columns(conn)
        _add_pending_meeting_columns(conn)
        _convert_posts_to_activity(conn)
        conn.commit()
    finally:
        conn.close()


def _add_pending_meeting_columns(conn) -> None:
    """Track threads waiting for a location response before booking."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
    pending = [
        ("pending_meeting_at", "TEXT"),   # ISO datetime of the tentative meeting
    ]
    for col, definition in pending:
        if col not in existing:
            conn.execute(f"ALTER TABLE threads ADD COLUMN {col} {definition}")


def _add_auto_reply_columns(conn) -> None:
    """Add columns that support automated inbox reply flow."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    pending = [
        ("auto_reply", "INTEGER NOT NULL DEFAULT 0"),  # 1 = sent automatically
    ]
    for col, definition in pending:
        if col not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {definition}")


def _add_redraft_columns(conn) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    pending = [
        ("redraft_instruction", "TEXT"),
        ("redraft_requested_at", "TEXT"),
    ]
    for col, definition in pending:
        if col not in existing:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {definition}")


def _convert_posts_to_activity(conn) -> None:
    """Convert legacy ``raw_json.posts`` (flat list of strings) into the typed
    ``raw_json.activity`` list, defaulting type to 'post'. Only touches rows
    that have ``posts`` but lack ``activity``.
    """
    rows = conn.execute(
        "SELECT id, raw_json FROM research WHERE raw_json IS NOT NULL"
    ).fetchall()
    for row in rows:
        try:
            raw = json.loads(row["raw_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if "activity" in raw or "posts" not in raw:
            continue
        raw["activity"] = [{"type": "post", "text": p} for p in raw.get("posts", [])]
        raw.pop("posts", None)
        conn.execute(
            "UPDATE research SET raw_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(raw, ensure_ascii=False), row["id"]),
        )
