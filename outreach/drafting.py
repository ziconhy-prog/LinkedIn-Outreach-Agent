"""Save opener drafts as messages in a thread for a prospect."""

from __future__ import annotations

from outreach.db.connection import get_connection


def save_opener(prospect_id: int, opener_text: str) -> int:
    """Find or create a thread for the prospect and save the opener as a draft.

    Returns the new message ID. The message is created with
    direction='outbound', role='opener', status='draft'. Sending happens
    later, only after explicit Telegram approval (Phase 5).
    """
    conn = get_connection()
    try:
        thread = conn.execute(
            "SELECT id FROM threads WHERE prospect_id = ? ORDER BY id DESC LIMIT 1",
            (prospect_id,),
        ).fetchone()
        if thread:
            thread_id = thread["id"]
        else:
            cur = conn.execute(
                "INSERT INTO threads (prospect_id, status) VALUES (?, 'queued')",
                (prospect_id,),
            )
            thread_id = cur.lastrowid

        cur = conn.execute(
            """
            INSERT INTO messages (thread_id, direction, role, content, status)
            VALUES (?, 'outbound', 'opener', ?, 'draft')
            """,
            (thread_id, opener_text),
        )
        message_id = cur.lastrowid
        conn.commit()
        if message_id is None:
            raise RuntimeError("Failed to insert message")
        return message_id
    finally:
        conn.close()


def get_drafts_for_prospect(prospect_id: int) -> list[dict]:
    """Return all draft messages for a prospect (newest first)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.role, m.content, m.status, m.created_at
            FROM messages m
            JOIN threads t ON t.id = m.thread_id
            WHERE t.prospect_id = ?
            ORDER BY m.id DESC
            """,
            (prospect_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
