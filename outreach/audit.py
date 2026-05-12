"""Audit log: every Playwright action gets a row in audit_log.

Logs are local-only and never include prospect names or message content
(per CLAUDE.md privacy rules). Targets reference internal IDs or URLs.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from outreach.db.connection import get_connection


def log(
    action: str,
    target: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Append one row to audit_log. Caller-managed connection optional."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    assert conn is not None
    try:
        conn.execute(
            """
            INSERT INTO audit_log (action, target, success, error_message)
            VALUES (?, ?, ?, ?)
            """,
            (action, target, 1 if success else 0, error_message),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()
