"""Telegram operator bot: authorization, dispatch, confirmation buttons, polling.

Only the operator (TELEGRAM_OPERATOR_USER_ID) can interact with the bot.
Unauthorized updates are silently dropped — no response, no log of content.

Natural language goes to telegram_brain (a conversational Claude agent with
per-chat memory). Slash commands are handled directly so the basics keep
working even if the Claude API is down:

  /start, /status   — system overview
  /queue            — show draft messages with content
  /show <id>        — show one draft's text
  /approve <id>     — stage a draft for sending (confirm button)
  /skip <id>        — mark a draft as skipped
  /edit <id> <txt>  — replace draft content directly (no AI)
  /redraft <id> <instruction> — AI rewrite of one draft
  /booked <name> <date> <time> <location> — book a meeting
  /health           — run the system health check
  /reset            — clear the bot's conversation memory
  /help             — list available commands

EVERY LinkedIn send goes through a Send/Cancel confirmation button — tapping
Send is the only way a message leaves the system.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from outreach import audit
from outreach.config import TELEGRAM_OPERATOR_USER_ID
from outreach.db.connection import get_connection
from outreach.telegram_client import (
    answer_callback_query,
    edit_message_text,
    get_updates,
    require_config,
    send_chat_action,
    send_message,
    send_operator_message,
)


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


# ---------------------------------------------------------------------------
# Send confirmation flow — the ONLY path to LinkedIn
# ---------------------------------------------------------------------------

# Serializes LinkedIn sends so two button taps can't drive the browser at once.
_SEND_LOCK = threading.Lock()


def request_send_confirmation(chat_id: int, message_id: int) -> None:
    """Show the draft with Send/Cancel buttons. Nothing is sent yet."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT m.id, m.status, m.content, p.name, p.company
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.id = ?
            """,
            (message_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        send_message(chat_id, f"Draft {message_id} not found.")
        return
    if row["status"] not in ("draft", "edited"):
        send_message(
            chat_id,
            f"{row['name']}'s draft is already '{row['status']}' — nothing to send.",
        )
        return

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Send it", "callback_data": f"send:{message_id}"},
            {"text": "❌ Cancel", "callback_data": f"cancel:{message_id}"},
        ]]
    }
    send_message(
        chat_id,
        f"Ready to send to {row['name']} ({row['company'] or 'company unknown'}):\n\n"
        f"{row['content']}\n\n"
        "Tap a button — nothing goes out until you confirm.",
        reply_markup=keyboard,
    )


def _do_send(chat_id: int, message_id: int, name: str) -> None:
    """Background worker: perform the actual LinkedIn send. Lock held by caller."""
    from outreach.linkedin.send import SendError, send_message as linkedin_send

    try:
        try:
            linkedin_send(message_id)
        except SendError as exc:
            # Roll back to draft so it reappears in the queue.
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE messages SET status = 'draft', approved_via = NULL, "
                    "approved_at = NULL WHERE id = ?",
                    (message_id,),
                )
                conn.commit()
            finally:
                conn.close()
            send_message(
                chat_id,
                f"❌ Send to {name} failed: {exc}\n\nThe draft is back in the queue.",
            )
            return
        except Exception as exc:  # noqa: BLE001 — never die silently in a thread
            send_message(
                chat_id,
                f"❌ Unexpected error sending to {name}: {exc}\n\n"
                f"Check the draft with /show {message_id}.",
            )
            return
        audit.log("telegram_command", target=f"approve_{message_id}")
        send_message(chat_id, f"✅ Sent to {name} on LinkedIn.")
    finally:
        _SEND_LOCK.release()


def handle_callback(update: dict[str, Any]) -> None:
    """Process a Send/Cancel button tap."""
    cq = update["callback_query"]
    data = cq.get("data", "") or ""
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    button_msg_id = msg.get("message_id")

    try:
        answer_callback_query(cq["id"])
    except Exception:  # noqa: BLE001
        pass

    action, _, id_str = data.partition(":")
    if chat_id is None or not id_str.isdigit():
        return
    message_id = int(id_str)

    def _replace_buttons(text: str) -> None:
        try:
            edit_message_text(chat_id, button_msg_id, text)
        except Exception:  # noqa: BLE001
            send_message(chat_id, text)

    if action == "cancel":
        _replace_buttons("Cancelled — the draft stays in the queue.")
        return

    if action != "send":
        return

    if not _SEND_LOCK.acquire(blocking=False):
        send_message(
            chat_id,
            "Still sending the previous one — wait for it to finish, then tap again.",
        )
        return

    # Atomically claim the draft so a double-tap can't send twice.
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE messages SET status = 'approved', approved_via = 'telegram', "
            "approved_at = CURRENT_TIMESTAMP WHERE id = ? AND status IN ('draft', 'edited')",
            (message_id,),
        )
        conn.commit()
        claimed = cur.rowcount > 0
        name_row = conn.execute(
            """
            SELECT p.name FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.id = ?
            """,
            (message_id,),
        ).fetchone()
    finally:
        conn.close()

    name = name_row["name"] if name_row else f"draft {message_id}"
    if not claimed:
        _SEND_LOCK.release()
        _replace_buttons(f"{name}'s draft was already handled — nothing sent.")
        return

    _replace_buttons(f"⏳ Sending to {name} on LinkedIn… (takes a minute, I'll confirm)")
    threading.Thread(
        target=_do_send, args=(chat_id, message_id, name), daemon=True
    ).start()


# ---------------------------------------------------------------------------
# Slash-command handlers (work without the Claude API)
# ---------------------------------------------------------------------------

def _help_text() -> str:
    return (
        "Just talk to me naturally — I understand things like:\n"
        "• \"what's in the queue?\"\n"
        "• \"make Keith's draft more casual\"\n"
        "• \"send Adibah\" (you'll get a confirm button)\n"
        "• \"skip Bernard and find me a new prospect\"\n"
        "• \"who is Xia Dan?\"\n"
        "• \"booked Keith tomorrow 2pm Bangsar\"\n"
        "• \"is everything ok?\"\n\n"
        "Backup commands (work even if the AI is down):\n"
        "/queue — drafts · /show <id> — one draft · /approve <id> — send\n"
        "/skip <id> · /edit <id> <text> · /redraft <id> <instruction>\n"
        "/health — system check · /reset — clear my memory · /help — this"
    )


def handle_show(chat_id: int, message_id: int) -> None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT m.id, m.status, m.content, p.name, p.company
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.id = ?
            """,
            (message_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        send_message(chat_id, f"Message {message_id} not found.")
        return
    send_message(
        chat_id,
        f"Draft {row['id']} — {row['name']} ({row['company'] or 'unknown'}) "
        f"[{row['status']}]\n\n{row['content']}",
    )


def handle_skip(chat_id: int, message_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE messages SET status = 'skipped' WHERE id = ? "
            "AND status IN ('draft', 'edited')",
            (message_id,),
        )
        conn.commit()
        skipped = cur.rowcount > 0
    finally:
        conn.close()
    if skipped:
        audit.log("telegram_command", target=f"skip_{message_id}")
        send_message(chat_id, f"⏭ Draft {message_id} skipped.")
    else:
        send_message(chat_id, f"Draft {message_id} not found or already handled.")


def handle_edit(chat_id: int, message_id: int, new_text: str) -> None:
    if not new_text.strip():
        send_message(chat_id, "Usage: /edit <id> <replacement text>")
        return
    text = new_text.strip()
    if len(text) > 300:
        send_message(
            chat_id,
            f"That's {len(text)} characters — over the 300-char LinkedIn limit. "
            "Shorten it and try again.",
        )
        return
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE messages SET content = ?, status = 'edited' WHERE id = ? "
            "AND status IN ('draft', 'edited')",
            (text, message_id),
        )
        conn.commit()
        edited = cur.rowcount > 0
    finally:
        conn.close()
    if edited:
        audit.log("telegram_command", target=f"edit_{message_id}")
        send_message(chat_id, f"✅ Draft {message_id} updated.")
    else:
        send_message(chat_id, f"Draft {message_id} not found or already handled.")


def handle_redraft(chat_id: int, message_id: int, instruction: str) -> None:
    """AI rewrite of one draft, addressed by ID (slash-command path)."""
    if not instruction.strip():
        send_message(
            chat_id,
            "What should I change? e.g. /redraft 5 make it more casual",
        )
        return
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT p.name FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.id = ? AND m.status IN ('draft', 'edited')
            """,
            (message_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        send_message(chat_id, f"Draft {message_id} not found or already handled.")
        return
    send_message(chat_id, f"⏳ Redrafting {row['name']}'s opener…")
    from outreach import telegram_brain

    result = telegram_brain.TOOL_IMPLS["redraft"](
        {"name": row["name"], "instruction": instruction.strip()},
        {"chat_id": chat_id, "staged_sends": []},
    )
    send_message(chat_id, result)


def handle_booked(chat_id: int, text: str) -> None:
    """Parse 'booked <name> <date> <time> <location>' and create a calendar event."""
    from outreach import calendar_client

    name_match = re.search(r"booked\s+([a-zA-Z\s]+?)(?:\d)", text, re.IGNORECASE)
    name_fragment = name_match.group(1).strip() if name_match else ""

    prospect = None
    if name_fragment:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT id, name, company, linkedin_url FROM prospects "
                "WHERE lower(name) LIKE ? LIMIT 1",
                (f"%{name_fragment.lower()}%",),
            ).fetchone()
            if row:
                prospect = dict(row)
        finally:
            conn.close()

    if not prospect:
        send_message(chat_id, "Couldn't find that prospect. Check the name and try again.")
        return

    success, message = calendar_client.parse_and_book(
        text=text,
        prospect_name=prospect["name"],
        company=prospect.get("company") or "",
        linkedin_url=prospect.get("linkedin_url") or "",
    )

    send_message(chat_id, message)
    if success:
        audit.log("calendar_booked", target=f"prospect:{prospect['id']}")


def _handle_slash(chat_id: int, text: str) -> bool:
    """Handle a known slash command directly. Returns False to fall through to the brain."""
    from outreach import telegram_brain

    cmd, msg_id, rest = _parse_action(text)
    ctx = {"chat_id": chat_id, "staged_sends": []}

    if cmd in ("start", "status"):
        send_message(
            chat_id,
            "SkillTrainer AI Outreach Bot\n\n"
            + telegram_brain.TOOL_IMPLS["get_status"]({}, ctx)
            + "\n\nJust type naturally — or /help for examples.",
        )
    elif cmd == "queue":
        send_message(chat_id, telegram_brain.TOOL_IMPLS["get_queue"]({}, ctx))
    elif cmd == "help":
        send_message(chat_id, _help_text())
    elif cmd == "health":
        send_message(chat_id, "Running a full check — the LinkedIn part takes ~20s…")
        send_message(chat_id, telegram_brain.TOOL_IMPLS["health_check"]({}, ctx))
    elif cmd == "reset":
        telegram_brain.reset_history(chat_id)
        send_message(chat_id, "Memory cleared — we're starting fresh.")
    elif cmd == "show" and msg_id is not None:
        handle_show(chat_id, msg_id)
    elif cmd == "approve" and msg_id is not None:
        request_send_confirmation(chat_id, msg_id)
    elif cmd == "skip" and msg_id is not None:
        handle_skip(chat_id, msg_id)
    elif cmd == "edit" and msg_id is not None:
        handle_edit(chat_id, msg_id, rest)
    elif cmd == "redraft" and msg_id is not None:
        handle_redraft(chat_id, msg_id, rest)
    elif cmd == "booked":
        handle_booked(chat_id, text.lstrip("/"))
    else:
        return False
    return True


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(update: dict[str, Any]) -> None:
    """Route one Telegram update — buttons, slash commands, or the brain."""
    if not is_authorized(update):
        return

    if "callback_query" in update:
        handle_callback(update)
        return

    message = update.get("message")
    if not message:
        return

    chat_id: int = message["chat"]["id"]
    text = (message.get("text") or "").strip()
    if not text:
        return

    audit.log("telegram_command", target=f"update_{update.get('update_id')}")

    if text.startswith("/") and _handle_slash(chat_id, text):
        return

    # Everything else: the conversational brain.
    try:
        send_chat_action(chat_id)
    except Exception:  # noqa: BLE001
        pass

    from outreach import telegram_brain

    result = telegram_brain.handle_message(chat_id, text.lstrip("/"))
    if result["reply"]:
        send_message(chat_id, result["reply"])
    for staged in result["staged_sends"]:
        request_send_confirmation(chat_id, staged["message_id"])


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

_GREETING = (
    "👋 Bot online (updated version).\n\n"
    "You can talk to me like a person now — I remember our conversation, so "
    "you can answer my questions naturally.\n\n"
    "Try:\n"
    "• \"what's in the queue?\"\n"
    "• \"make Keith's draft more casual\"\n"
    "• \"send Adibah\" — I'll show a confirm button first\n"
    "• \"is everything ok?\" — full system check\n\n"
    "I will NEVER send anything to LinkedIn without you tapping a confirm button."
)


def run_polling_loop(
    stop_after_seconds: int | None = None,
    once: bool = False,
) -> None:
    """Long-poll getUpdates and dispatch commands. Blocks until Ctrl-C."""
    from outreach.db import migrations

    migrations.run()
    require_config()

    if not once:
        try:
            send_operator_message(_GREETING)
        except Exception as exc:  # noqa: BLE001
            print(f"Greeting not sent: {exc}")

    print("Telegram polling started. Press Ctrl-C to stop.")
    offset: int | None = None
    start = time.monotonic()

    # Errors that signal transient network/server issues — never kill the
    # loop for these; back off and retry. Anything else is treated as fatal.
    import socket as _socket
    import urllib.error as _urlerr

    transient_errors = (
        TimeoutError,
        ConnectionResetError,
        ConnectionError,
        _socket.timeout,
        _urlerr.URLError,
    )

    consecutive_failures = 0
    try:
        while True:
            if stop_after_seconds is not None:
                if time.monotonic() - start > stop_after_seconds:
                    break

            poll_timeout = 1 if once else 25
            try:
                updates = get_updates(offset=offset, timeout=poll_timeout)
                consecutive_failures = 0
            except transient_errors as exc:
                consecutive_failures += 1
                # Exponential backoff capped at 60s; do not crash.
                backoff = min(2 ** min(consecutive_failures, 6), 60)
                print(
                    f"[poll] transient network error ({type(exc).__name__}: {exc}); "
                    f"retry #{consecutive_failures} in {backoff}s"
                )
                time.sleep(backoff)
                continue

            for update in updates:
                try:
                    dispatch(update)
                except Exception as exc:  # noqa: BLE001
                    # One bad update must not kill the bot.
                    print(f"[dispatch] error on update {update.get('update_id')}: {exc}")
                    try:
                        chat = (update.get("message") or {}).get("chat", {})
                        if chat.get("id"):
                            send_message(
                                chat["id"],
                                f"⚠️ That one tripped me up ({type(exc).__name__}). Try again?",
                            )
                    except Exception:  # noqa: BLE001
                        pass
                offset = update["update_id"] + 1

            if once:
                print(f"Fetched {len(updates)} update(s).")
                break

    except KeyboardInterrupt:
        print("\nPolling stopped.")
