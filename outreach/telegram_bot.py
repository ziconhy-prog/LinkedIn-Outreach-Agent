"""Telegram operator bot: authorization, command dispatch, polling loop.

Only the operator (TELEGRAM_OPERATOR_USER_ID) can interact with the bot.
Unauthorized updates are silently dropped — no response, no log of content.
No LinkedIn send actions are in scope here.
"""

from __future__ import annotations

import time
from typing import Any

from outreach import audit
from outreach.config import TELEGRAM_OPERATOR_USER_ID
from outreach.db.connection import get_connection
from outreach.telegram_client import get_updates, require_config, send_message


def is_authorized(update: dict[str, Any]) -> bool:
    """Return True only if the update originates from the configured operator."""
    if not TELEGRAM_OPERATOR_USER_ID:
        return False
    sender_id: Any = None
    if "message" in update:
        sender_id = update["message"].get("from", {}).get("id")
    elif "callback_query" in update:
        sender_id = update["callback_query"].get("from", {}).get("id")
    return str(sender_id) == TELEGRAM_OPERATOR_USER_ID


def _status_text() -> str:
    conn = get_connection()
    try:
        draft_count = conn.execute(
            "SELECT count(*) FROM messages WHERE status = 'draft'"
        ).fetchone()[0]
        active_threads = conn.execute(
            "SELECT count(*) FROM threads WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        conn.close()
    return (
        f"SkillTrainer AI Outreach Bot\n\n"
        f"Drafts awaiting approval: {draft_count}\n"
        f"Active threads: {active_threads}\n\n"
        f"Commands: /queue"
    )


def _queue_text() -> str:
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT count(*) FROM messages WHERE status = 'draft'"
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT m.id, p.name, p.company, m.content
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status = 'draft'
            ORDER BY m.created_at ASC
            LIMIT 5
            """
        ).fetchall()
    finally:
        conn.close()

    if total == 0:
        return "No drafts in queue."

    lines = [f"Drafts: {total} total\n"]
    for row in rows:
        lines.append(f"[{row['id']}] {row['name']} — {row['company'] or 'unknown'}")
        lines.append(f"{row['content']}")
        lines.append("")
    if total > 5:
        lines.append(f"... and {total - 5} more")
    return "\n".join(lines).strip()


def handle_start(chat_id: int) -> None:
    send_message(chat_id, _status_text())


def handle_queue(chat_id: int) -> None:
    send_message(chat_id, _queue_text())


def dispatch(update: dict[str, Any]) -> None:
    """Route one Telegram update. Silently drops unauthorized updates."""
    if not is_authorized(update):
        return

    message = update.get("message")
    if not message:
        return

    chat_id: int = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    update_id = update.get("update_id")

    if text == "/start":
        audit.log("telegram_command", target=f"update_{update_id}")
        handle_start(chat_id)
    elif text == "/queue":
        audit.log("telegram_command", target=f"update_{update_id}")
        handle_queue(chat_id)
    # All other text: silent drop — no response, no log of message content


def run_polling_loop(
    stop_after_seconds: int | None = None,
    once: bool = False,
) -> None:
    """Long-poll getUpdates and dispatch commands. Blocks until Ctrl-C or stop condition."""
    require_config()
    print("Telegram polling started. Press Ctrl-C to stop.")
    offset: int | None = None
    start = time.monotonic()

    try:
        while True:
            if stop_after_seconds is not None:
                if time.monotonic() - start > stop_after_seconds:
                    break

            poll_timeout = 1 if once else 25
            updates = get_updates(offset=offset, timeout=poll_timeout)
            for update in updates:
                dispatch(update)
                offset = update["update_id"] + 1

            if once:
                print(f"Fetched {len(updates)} update(s).")
                break

    except KeyboardInterrupt:
        print("\nPolling stopped.")
