"""Telegram operator bot: authorization, command dispatch, polling loop.

Only the operator (TELEGRAM_OPERATOR_USER_ID) can interact with the bot.
Unauthorized updates are silently dropped — no response, no log of content.
No LinkedIn send actions are in scope here.

Supported commands:
  /start           — system status
  /queue           — show draft messages with content
  /skip <id>       — mark a draft as skipped
  /edit <id> <txt> — replace draft content directly (no LLM)
  /redraft <id> <instruction> — queue a redraft request for Claude Code
  /help            — list available commands

Natural-language equivalents for status/queue/help are also recognized.
"""

from __future__ import annotations

import re
import time
from typing import Any

from outreach import audit
from outreach.config import TELEGRAM_OPERATOR_USER_ID
from outreach.db.connection import get_connection
from outreach.telegram_client import get_updates, require_config, send_message


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------

def _parse_action(text: str) -> tuple[str, int | None, str]:
    """Parse '/command id optional text' → (command, id_or_None, rest).

    Examples:
      '/skip 2'            → ('skip', 2, '')
      '/edit 2 new text'   → ('edit', 2, 'new text')
      '/redraft 2 try X'   → ('redraft', 2, 'try X')
    """
    parts = text.lstrip("/").split(None, 2)
    cmd = parts[0].lower() if parts else ""
    msg_id: int | None = None
    rest = ""
    if len(parts) >= 2:
        try:
            msg_id = int(parts[1])
        except ValueError:
            rest = " ".join(parts[1:])
            return cmd, None, rest
    if len(parts) >= 3:
        rest = parts[2]
    return cmd, msg_id, rest


# Keyword sets for fuzzy intent detection.
_QUEUE_WORDS = frozenset(["queue", "draft", "drafts", "pending", "waiting", "list"])
_STATUS_WORDS = frozenset(["status", "start", "summary", "report", "active", "overview"])
_HELP_PHRASES = ("help", "command", "what can", "option")


def _detect_intent(text: str) -> str | None:
    """Map natural-language text to a command name, or None if unrecognised."""
    lower = text.lower()
    words = set(lower.split())
    if words & _QUEUE_WORDS:
        return "queue"
    if words & _STATUS_WORDS:
        return "start"
    if any(phrase in lower for phrase in _HELP_PHRASES):
        return "help"
    return None


# ---------------------------------------------------------------------------
# Reply builders
# ---------------------------------------------------------------------------

def _status_text() -> str:
    conn = get_connection()
    try:
        draft_count = conn.execute(
            "SELECT count(*) FROM messages WHERE status = 'draft'"
        ).fetchone()[0]
        edited_count = conn.execute(
            "SELECT count(*) FROM messages WHERE status = 'edited'"
        ).fetchone()[0]
        active_threads = conn.execute(
            "SELECT count(*) FROM threads WHERE status = 'active'"
        ).fetchone()[0]
        redraft_count = conn.execute(
            "SELECT count(*) FROM messages WHERE redraft_instruction IS NOT NULL"
            " AND status NOT IN ('sent', 'skipped')"
        ).fetchone()[0]
    finally:
        conn.close()
    lines = [
        "SkillTrainer AI Outreach Bot\n",
        f"Drafts awaiting approval: {draft_count + edited_count}",
        f"Active threads: {active_threads}",
    ]
    if redraft_count:
        lines.append(f"Pending redraft requests: {redraft_count} (run `outreach inbox`)")
    lines.append("\nCommands: /queue  /skip  /edit  /redraft  /help")
    return "\n".join(lines)


def _queue_text() -> str:
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT count(*) FROM messages WHERE status IN ('draft', 'edited')"
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT m.id, m.status, p.name, p.company, m.content
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status IN ('draft', 'edited')
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
        tag = " [edited]" if row["status"] == "edited" else ""
        lines.append(f"[{row['id']}]{tag} {row['name']} — {row['company'] or 'unknown'}")
        lines.append(row["content"])
        lines.append("")
    if total > 5:
        lines.append(f"... and {total - 5} more")
    lines.append("\nActions: /skip <id>  /edit <id> <text>  /redraft <id> <instruction>")
    return "\n".join(lines).strip()


def _help_text() -> str:
    return (
        "Available commands:\n\n"
        "/start — system status\n"
        "/queue — show drafts with content\n"
        "/skip <id> — skip a draft\n"
        "/edit <id> <text> — replace draft text (no AI needed)\n"
        "/redraft <id> <instruction> — queue an AI redraft for Claude Code\n"
        "/help — this message\n\n"
        "Natural language also works for status and queue:\n"
        "'show queue', 'what's pending', 'status', etc."
    )


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def handle_start(chat_id: int) -> None:
    send_message(chat_id, _status_text())


def handle_queue(chat_id: int) -> None:
    send_message(chat_id, _queue_text())


def handle_help(chat_id: int) -> None:
    send_message(chat_id, _help_text())


def handle_skip(chat_id: int, message_id: int) -> None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, status FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            send_message(chat_id, f"Message {message_id} not found.")
            return
        if row["status"] not in ("draft", "edited"):
            send_message(chat_id, f"Message {message_id} is already '{row['status']}' — nothing to skip.")
            return
        conn.execute(
            "UPDATE messages SET status = 'skipped' WHERE id = ?", (message_id,)
        )
        conn.commit()
        audit.log("telegram_command", target=f"skip_{message_id}")
        send_message(chat_id, f"⏭ Draft {message_id} skipped.")
    finally:
        conn.close()


def handle_edit(chat_id: int, message_id: int, new_text: str) -> None:
    if not new_text.strip():
        send_message(chat_id, "Usage: /edit <id> <replacement text>")
        return
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, status FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            send_message(chat_id, f"Message {message_id} not found.")
            return
        if row["status"] not in ("draft", "edited"):
            send_message(chat_id, f"Message {message_id} has status '{row['status']}' — can only edit draft or edited messages.")
            return
        conn.execute(
            "UPDATE messages SET content = ?, status = 'edited' WHERE id = ?",
            (new_text.strip(), message_id),
        )
        conn.commit()
        audit.log("telegram_command", target=f"edit_{message_id}")
        send_message(chat_id, f"✅ Draft {message_id} updated. Run /queue to review.")
    finally:
        conn.close()


def handle_redraft(chat_id: int, message_id: int, instruction: str) -> None:
    if not instruction.strip():
        send_message(chat_id, "Usage: /redraft <id> <instruction>\nExample: /redraft 2 try the freight angle instead")
        return
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, status FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            send_message(chat_id, f"Message {message_id} not found.")
            return
        if row["status"] in ("sent", "skipped"):
            send_message(chat_id, f"Message {message_id} is already '{row['status']}' — can't redraft.")
            return
        conn.execute(
            """
            UPDATE messages
            SET redraft_instruction = ?, redraft_requested_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (instruction.strip(), message_id),
        )
        conn.commit()
        audit.log("telegram_command", target=f"redraft_{message_id}")
        send_message(
            chat_id,
            f"📝 Redraft queued for draft {message_id}.\n"
            f"Instruction: {instruction.strip()}\n\n"
            f"Run `outreach inbox` in Claude Code to process it.",
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

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

    if not text:
        return

    # --- Explicit slash commands ---
    if text.startswith("/"):
        cmd, msg_id, rest = _parse_action(text)

        if cmd == "start":
            audit.log("telegram_command", target=f"update_{update_id}")
            handle_start(chat_id)

        elif cmd == "queue":
            audit.log("telegram_command", target=f"update_{update_id}")
            handle_queue(chat_id)

        elif cmd == "help":
            audit.log("telegram_command", target=f"update_{update_id}")
            handle_help(chat_id)

        elif cmd == "skip":
            if msg_id is None:
                send_message(chat_id, "Usage: /skip <id>")
            else:
                audit.log("telegram_command", target=f"update_{update_id}")
                handle_skip(chat_id, msg_id)

        elif cmd == "edit":
            if msg_id is None:
                send_message(chat_id, "Usage: /edit <id> <replacement text>")
            else:
                audit.log("telegram_command", target=f"update_{update_id}")
                handle_edit(chat_id, msg_id, rest)

        elif cmd == "redraft":
            if msg_id is None:
                send_message(chat_id, "Usage: /redraft <id> <instruction>")
            else:
                audit.log("telegram_command", target=f"update_{update_id}")
                handle_redraft(chat_id, msg_id, rest)

        else:
            send_message(chat_id, f"Unknown command /{cmd}. Try /help.")

    # --- Natural-language fallback ---
    else:
        intent = _detect_intent(text)
        if intent == "queue":
            audit.log("telegram_command", target=f"update_{update_id}")
            handle_queue(chat_id)
        elif intent == "start":
            audit.log("telegram_command", target=f"update_{update_id}")
            handle_start(chat_id)
        elif intent == "help":
            audit.log("telegram_command", target=f"update_{update_id}")
            handle_help(chat_id)
        else:
            send_message(chat_id, "Not sure what you mean. Try /help for available commands.")


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

def run_polling_loop(
    stop_after_seconds: int | None = None,
    once: bool = False,
) -> None:
    """Long-poll getUpdates and dispatch commands. Blocks until Ctrl-C."""
    from outreach.db import migrations
    migrations.run()

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
