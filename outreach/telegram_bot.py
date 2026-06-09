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


import re as _re

# Last message ID shown/queued — used as context for "send it" without a name.
_context_message_id: int | None = None


def _set_context(message_id: int | None) -> None:
    global _context_message_id
    _context_message_id = message_id


# ---------------------------------------------------------------------------
# Natural language intent detection
# ---------------------------------------------------------------------------

_QUEUE_WORDS = frozenset([
    "queue", "draft", "drafts", "pending", "waiting", "list",
    "show me", "what's pending", "whats pending", "anything waiting",
])
_STATUS_WORDS = frozenset([
    "status", "start", "summary", "report", "active", "overview",
    "how's it going", "what's happening", "update",
])
_APPROVE_WORDS = frozenset([
    "send", "approve", "ship",
    "looks good", "send it", "send this", "go ahead", "do it",
    "send that", "fire it", "fire away",
])
_SKIP_WORDS = frozenset([
    "skip", "ignore", "drop", "cancel", "don't send", "dont send",
    "not this one", "leave it", "pass", "delete", "remove",
    "don't like", "dont like", "not good", "scrap", "discard",
])
_EDIT_WORDS = frozenset([
    "edit", "change", "update", "replace", "rewrite", "tweak", "fix",
    "adjust", "modify",
])
_HELP_WORDS = frozenset(["help", "commands", "options", "what can you do"])
_BOOKED_PHRASES = frozenset([
    "booked", "meeting confirmed", "confirmed meeting", "set a meeting",
    "locked in a meeting", "scheduled",
])
_PROSPECT_PHRASES = frozenset([
    "run a search", "find prospects", "search for prospects",
    "pull out", "pull prospects", "draft openers", "find new leads",
    "start prospecting", "run prospecting", "find me prospects",
    "new prospects", "generate openers", "search and draft",
])


def _detect_intent(text: str) -> str | None:
    """Map natural-language text to an intent string."""
    lower = text.lower()
    words = set(lower.split())

    # Prospecting trigger — check before others
    if any(phrase in lower for phrase in _PROSPECT_PHRASES):
        return "prospect"
    # Booked first — very specific
    if any(phrase in lower for phrase in _BOOKED_PHRASES):
        return "booked"
    # Skip/delete before approve — must catch "delete" before anything else
    if words & _SKIP_WORDS:
        return "skip"
    # Edit before approve
    if words & _EDIT_WORDS:
        return "edit"
    # Approve / send — only explicit send words, no ambiguous ones
    if words & _APPROVE_WORDS:
        return "approve"
    # Queue / drafts
    if words & _QUEUE_WORDS:
        return "queue"
    # Status
    if words & _STATUS_WORDS:
        return "start"
    # Help
    if words & _HELP_WORDS:
        return "help"
    return None


# ---------------------------------------------------------------------------
# Name extraction helpers
# ---------------------------------------------------------------------------

def _extract_name_fragment(text: str, trigger_words: set) -> str:
    """Strip trigger words from text and return the remaining name fragment."""
    lower = text.lower()
    remaining = lower
    for word in sorted(trigger_words, key=len, reverse=True):
        remaining = remaining.replace(word, " ")
    # Also strip common filler words
    for filler in ("to", "the", "message", "for", "it", "this", "that", "now"):
        remaining = _re.sub(rf"\b{filler}\b", " ", remaining)
    return remaining.strip()


def _find_draft_by_name(name_fragment: str) -> int | None:
    """Return a draft message ID using fuzzy token matching on prospect name.

    Matches if ANY word in name_fragment matches ANY word in the prospect name.
    e.g. "dan" matches "Xia Dan Duar", "xia" matches too.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.id, p.name
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status IN ('draft', 'edited')
            ORDER BY m.created_at ASC
            """
        ).fetchall()

        fragment = name_fragment.lower().strip()
        if not fragment:
            return None

        # Try exact substring first
        for row in rows:
            if fragment in row["name"].lower():
                return row["id"]

        # Token overlap — any word in fragment matches any word in prospect name
        fragment_tokens = set(fragment.split())
        for row in rows:
            name_tokens = set(row["name"].lower().split())
            if fragment_tokens & name_tokens:
                return row["id"]

        return None
    finally:
        conn.close()


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
    lines.append("\nJust type naturally — 'show queue', 'send Xia Dan', 'skip Bernard', etc.")
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
        _set_context(None)
        return "No drafts in queue."

    lines = [f"Drafts: {total} total\n"]
    last_id = None
    for row in rows:
        tag = " [edited]" if row["status"] == "edited" else ""
        lines.append(f"{row['name']} ({row['company'] or 'unknown'}){tag}")
        lines.append(row["content"])
        lines.append("")
        last_id = row["id"]
    if total > 5:
        lines.append(f"... and {total - 5} more")
    lines.append("Reply naturally — e.g. 'send Xia Dan', 'skip Bernard', 'send it' (if one draft)")
    _set_context(last_id if total == 1 else None)
    return "\n".join(lines).strip()


def _help_text() -> str:
    return (
        "Available commands:\n\n"
        "/start — system status\n"
        "/queue — show drafts with content\n"
        "/show <id> — show just the draft text (copy and tweak it)\n"
        "/approve <id> — approve and send a draft to LinkedIn\n"
        "/skip <id> — skip a draft\n"
        "/edit <id> <text> — replace draft text (no AI needed)\n"
        "/redraft <id> <instruction> — queue an AI redraft for Claude Code\n"
        "/booked <name> <date> <time> <location> — book a meeting in Google Calendar\n"
        "  Example: booked Xia Dan 20 May 2pm Bangsar\n"
        "/help — this message\n\n"
        "Natural language also works for status, queue, and booking:\n"
        "'show queue', 'booked Xia Dan 20 May 2pm Bangsar', etc."
    )


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def handle_booked(chat_id: int, text: str) -> None:
    """Parse 'booked <name> <date> <time> <location>' and create a calendar event."""
    from outreach import calendar_client
    conn = get_connection()
    try:
        # Find the prospect by name fragment from the text.
        name_match = __import__('re').search(
            r'booked\s+([a-zA-Z\s]+?)(?:\d)', text, __import__('re').IGNORECASE
        )
        name_fragment = name_match.group(1).strip() if name_match else ""

        prospect = None
        if name_fragment:
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


def handle_prospect(chat_id: int) -> None:
    """Trigger the full prospecting pipeline in a background thread."""
    import threading
    from outreach import prospecting_pipeline
    from outreach.telegram_client import send_message as _send

    def _notify(msg: str) -> None:
        _send(chat_id, msg)

    send_message(chat_id, "On it. Searching LinkedIn and drafting openers — I'll update you as I go.")

    def _run() -> None:
        prospecting_pipeline.run(limit=3, notify=_notify)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def notify_escalation(label: str, thread_id: int, preview: str) -> None:
    """Send an escalation alert to the operator. Called by inbox_handler."""
    from outreach.config import TELEGRAM_OPERATOR_USER_ID
    if not TELEGRAM_OPERATOR_USER_ID:
        return
    text = (
        f"⚠️ NEEDS YOU — {label}\n\n"
        f"Thread {thread_id}:\n\"{preview[:200]}\"\n\n"
        f"Run /queue to review."
    )
    try:
        send_message(int(TELEGRAM_OPERATOR_USER_ID), text)
    except Exception:  # noqa: BLE001
        pass


def handle_start(chat_id: int) -> None:
    send_message(chat_id, _status_text())


def handle_queue(chat_id: int) -> None:
    send_message(chat_id, _queue_text())


def handle_help(chat_id: int) -> None:
    send_message(chat_id, _help_text())


def handle_approve(chat_id: int, message_id: int) -> None:
    from outreach.linkedin.send import SendError, send_message as linkedin_send
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, status FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if not row:
            send_message(chat_id, f"Message {message_id} not found.")
            return
        if row["status"] not in ("draft", "edited"):
            send_message(chat_id, f"Message {message_id} is already '{row['status']}' — nothing to approve.")
            return
        # Mark approved before sending so send.py accepts it.
        conn.execute(
            "UPDATE messages SET status = 'approved', approved_via = 'telegram', "
            "approved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (message_id,),
        )
        conn.commit()
    finally:
        conn.close()

    send_message(chat_id, f"⏳ Sending message {message_id} to LinkedIn…")
    try:
        linkedin_send(message_id)
        audit.log("telegram_command", target=f"approve_{message_id}")
        send_message(chat_id, f"✅ Sent on LinkedIn.")
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
        send_message(chat_id, f"❌ Send failed: {exc}\n\nDraft restored to queue.")


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
        if not row:
            send_message(chat_id, f"Message {message_id} not found.")
            return
        header = f"Draft {row['id']} — {row['name']} ({row['company'] or 'unknown'}) [{row['status']}]\n\n"
        body = row["content"]
        footer = f"\n\nTo edit: /edit {row['id']} <your new text>"
        send_message(chat_id, header + body + footer)
    finally:
        conn.close()


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


def handle_redraft_all(chat_id: int, instruction: str) -> None:
    """Redraft every pending draft in the queue with the same instruction."""
    if not instruction.strip():
        send_message(chat_id, "What style/angle should I apply to all drafts? "
                              "Say 'redraft all — [your direction]'.")
        return

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.content, p.id AS prospect_id, p.name, p.company,
                   p.city, p.area, r.brief_md
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            LEFT JOIN research r ON r.prospect_id = p.id
            WHERE m.status IN ('draft', 'edited')
            ORDER BY m.id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        send_message(chat_id, "No drafts in the queue to redraft.")
        return

    send_message(chat_id, f"⏳ Redrafting {len(rows)} drafts with: {instruction.strip()}")

    from outreach import drafter
    summary = {"updated": 0, "skipped": 0, "too_long": 0, "no_brief": 0}

    for row in rows:
        if not row["brief_md"]:
            summary["no_brief"] += 1
            send_message(chat_id, f"⚠️ Skipped {row['name']} — no research brief.")
            continue

        prospect = {
            "name": row["name"],
            "company": row["company"] or "",
            "city": row["city"] or "",
            "area": row["area"] or "",
        }
        try:
            new_text = drafter.regenerate_opener(
                prospect=prospect,
                brief=row["brief_md"],
                current_draft=row["content"],
                instruction=instruction.strip(),
            )
        except Exception as exc:  # noqa: BLE001
            summary["skipped"] += 1
            send_message(chat_id, f"❌ {row['name']} redraft failed: {exc}")
            continue

        if len(new_text) > 300:
            summary["too_long"] += 1
            send_message(
                chat_id,
                f"⚠️ {row['name']} new draft is {len(new_text)} chars (over 300). Skipped.",
            )
            continue

        conn = get_connection()
        try:
            conn.execute(
                """
                UPDATE messages
                SET content = ?, status = 'edited',
                    redraft_instruction = NULL, redraft_requested_at = NULL
                WHERE id = ?
                """,
                (new_text, row["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        summary["updated"] += 1
        send_message(
            chat_id,
            f"✅ {row['name']} ({len(new_text)} chars):\n{new_text}",
        )

    audit.log("telegram_command", target="redraft_all")
    send_message(
        chat_id,
        f"Done. Updated: {summary['updated']} · Too long: {summary['too_long']} · "
        f"No brief: {summary['no_brief']} · Failed: {summary['skipped']}\n\n"
        "Say 'show queue' to review, then 'send [name]' for each you want to send.",
    )


def handle_restore(chat_id: int, name_fragment: str) -> None:
    """Restore the most recent skipped draft for a prospect back to draft status."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT m.id, p.name
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status = 'skipped'
              AND lower(p.name) LIKE ?
            ORDER BY m.created_at DESC
            LIMIT 1
            """,
            (f"%{name_fragment.lower()}%",),
        ).fetchone()
        if not row:
            send_message(chat_id, f"No skipped draft found for '{name_fragment}'.")
            return
        conn.execute("UPDATE messages SET status = 'draft' WHERE id = ?", (row["id"],))
        conn.commit()
        send_message(chat_id, f"Restored draft for {row['name']}. Say 'show queue' to review.")
    finally:
        conn.close()


def handle_redraft(chat_id: int, message_id: int, instruction: str) -> None:
    """Generate a new opener live via Claude API and replace the draft in place."""
    if not instruction.strip():
        send_message(chat_id, "What should I change? e.g. 'redraft Keith — lead with the founder operations angle'")
        return

    # Pull everything we need to regenerate.
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT m.id, m.status, m.content,
                   p.id AS prospect_id, p.name, p.company, p.city, p.area,
                   r.brief_md
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            LEFT JOIN research r ON r.prospect_id = p.id
            WHERE m.id = ?
            """,
            (message_id,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        send_message(chat_id, f"Message {message_id} not found.")
        return
    if row["status"] in ("sent", "skipped"):
        send_message(chat_id, f"Message {message_id} is '{row['status']}' — can't redraft.")
        return
    if not row["brief_md"]:
        send_message(chat_id, f"No research brief for {row['name']} — can't generate a new opener.")
        return

    send_message(chat_id, f"⏳ Redrafting opener for {row['name']}…")

    prospect = {
        "name": row["name"],
        "company": row["company"] or "",
        "city": row["city"] or "",
        "area": row["area"] or "",
    }

    try:
        from outreach import drafter
        new_text = drafter.regenerate_opener(
            prospect=prospect,
            brief=row["brief_md"],
            current_draft=row["content"],
            instruction=instruction.strip(),
        )
    except Exception as exc:  # noqa: BLE001
        send_message(chat_id, f"❌ Redraft failed: {exc}")
        return

    # Enforce char limit before persisting.
    if len(new_text) > 300:
        send_message(
            chat_id,
            f"⚠️ Generated draft is {len(new_text)} chars (over the 300 cap). "
            "Try a tighter instruction or ask me to shorten it.",
        )
        return

    # Persist the new content + clear the queued instruction.
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE messages
            SET content = ?, status = 'edited',
                redraft_instruction = NULL, redraft_requested_at = NULL
            WHERE id = ?
            """,
            (new_text, message_id),
        )
        conn.commit()
    finally:
        conn.close()
    audit.log("telegram_command", target=f"redraft_{message_id}")

    send_message(
        chat_id,
        f"✅ New draft for {row['name']} ({len(new_text)} chars):\n\n"
        f"{new_text}\n\n"
        f"Say 'send {row['name'].split()[0]}' to send, or redraft again with a new angle.",
    )


# ---------------------------------------------------------------------------
# Research display helper
# ---------------------------------------------------------------------------

def _show_research(chat_id: int, name_fragment: str) -> None:
    """Show all available info for a prospect matched by name fragment."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT p.id, p.name, p.company, p.profession, p.city, p.area,
                   p.category, p.linkedin_url, p.enrichment_status,
                   r.brief_md,
                   m.content AS draft_content
            FROM prospects p
            LEFT JOIN research r ON r.prospect_id = p.id
            LEFT JOIN threads t ON t.prospect_id = p.id
            LEFT JOIN messages m ON m.thread_id = t.id
                AND m.status IN ('draft', 'edited')
            WHERE lower(p.name) LIKE ?
            ORDER BY p.id ASC
            LIMIT 1
            """,
            (f"%{name_fragment.lower()}%",),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        send_message(chat_id, f"No prospect found matching '{name_fragment}'.")
        return

    lines = [f"*{row['name']}*"]
    if row["company"]:
        lines.append(f"Company: {row['company']}")
    if row["profession"]:
        lines.append(f"Role: {row['profession']}")
    location = row["city"] or row["area"] or ""
    if location:
        lines.append(f"Location: {location}")
    if row["category"]:
        lines.append(f"BNI category: {row['category']}")
    if row["linkedin_url"]:
        lines.append(f"LinkedIn: {row['linkedin_url']}")

    if row["brief_md"]:
        lines.append(f"\n*Research brief:*\n{row['brief_md']}")

    if row["draft_content"]:
        lines.append(f"\n*Draft opener:*\n{row['draft_content']}")
    elif row["enrichment_status"] == "pending":
        lines.append("\n_Not yet enriched — run prospecting to get research + draft._")

    send_message(chat_id, "\n".join(lines))


# ---------------------------------------------------------------------------
# Dispatch — brain-powered natural language routing
# ---------------------------------------------------------------------------

def _resolve_message_id(text: str, trigger_words: set) -> int | None:
    """Try to find a message ID from text — by number, name, or context."""
    num = _re.search(r'\d+', text)
    if num:
        return int(num.group())
    name_fragment = _extract_name_fragment(text, trigger_words)
    if name_fragment:
        found = _find_draft_by_name(name_fragment)
        if found:
            return found
    return _context_message_id


def _resolve_by_name(target_name: str) -> int | None:
    """Resolve a brain-extracted name fragment to a draft message ID."""
    if target_name:
        found = _find_draft_by_name(target_name)
        if found:
            return found
    return _context_message_id


def dispatch(update: dict[str, Any]) -> None:
    """Route one Telegram update using Claude brain for intent detection.

    Falls back to keyword detection if the API key is missing or the call fails.
    """
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

    clean = text.lstrip("/")
    audit.log("telegram_command", target=f"update_{update_id}")

    # --- Brain-powered intent routing ---
    from outreach import telegram_brain
    result = telegram_brain.parse_intent(clean)
    intent = result["intent"]
    target_name = result["target_name"]
    print(f"[brain] msg={clean!r} → intent={intent} target={target_name!r} "
          f"replacement={result['find_replacement']} new_text={bool(result['new_text'])}")

    if intent == "start_prospecting":
        handle_prospect(chat_id)

    elif intent == "show_queue":
        handle_queue(chat_id)

    elif intent == "show_status":
        handle_start(chat_id)

    elif intent == "help":
        handle_help(chat_id)

    elif intent == "book_meeting":
        booking_text = result["instruction"] or clean
        handle_booked(chat_id, booking_text)

    elif intent == "send_draft":
        msg_id = _resolve_by_name(target_name)
        if msg_id:
            handle_approve(chat_id, msg_id)
        else:
            handle_queue(chat_id)
            send_message(chat_id, "Who should I send to? Reply with a name or say 'send [name]'.")

    elif intent == "restore_draft":
        if target_name:
            handle_restore(chat_id, target_name)
        else:
            send_message(chat_id, "Which skipped draft should I restore? Say 'bring back [name]'.")

    elif intent == "skip_draft":
        msg_id = _resolve_by_name(target_name)
        if msg_id:
            handle_skip(chat_id, msg_id)
            if result["find_replacement"]:
                send_message(chat_id, "Finding a replacement prospect...")
                import threading
                from outreach import prospecting_pipeline
                from outreach.telegram_client import send_message as _send
                def _notify(msg): _send(chat_id, msg)
                threading.Thread(
                    target=lambda: prospecting_pipeline.run(limit=1, notify=_notify),
                    daemon=True,
                ).start()
        else:
            handle_queue(chat_id)
            send_message(chat_id, "Which draft to skip? Say 'delete [name]' or 'skip [name]'.")

    elif intent == "edit_draft":
        msg_id = _resolve_by_name(target_name)
        new_text = result["new_text"].strip()
        if msg_id and new_text:
            handle_edit(chat_id, msg_id, new_text)
        elif msg_id:
            handle_show(chat_id, msg_id)
            send_message(chat_id, "What should it say? Reply with the new text.")
        else:
            handle_queue(chat_id)
            send_message(chat_id, "Which draft to edit? Say 'edit [name] to say [new text]'.")

    elif intent == "redraft":
        msg_id = _resolve_by_name(target_name)
        instruction = result["instruction"].strip()
        if msg_id and instruction:
            handle_redraft(chat_id, msg_id, instruction)
        elif msg_id:
            send_message(chat_id, "What should I change about it? Give me a direction.")
        else:
            handle_queue(chat_id)
            send_message(chat_id, "Which draft to redraft? Say 'redraft [name] — try the [angle] instead'.")

    elif intent == "redraft_all":
        handle_redraft_all(chat_id, result["instruction"])

    elif intent == "show_research":
        if target_name:
            _show_research(chat_id, target_name)
        else:
            send_message(chat_id, "Which prospect's research should I show? Say 'show research for [name]'.")

    elif intent in ("clarify", "chat"):
        reply = result["reply"]
        send_message(chat_id, reply or (
            "Not sure what you mean. Try:\n"
            "• 'show queue' — see pending drafts\n"
            "• 'send Xia Dan' — send a draft\n"
            "• 'skip Bernard' — skip a draft\n"
            "• 'edit Xia Dan to say...' — update a draft\n"
            "• 'status' — see overview"
        ))

    else:
        send_message(chat_id,
            "Not sure what you mean. Try:\n"
            "• 'show queue' — see pending drafts\n"
            "• 'send Xia Dan' — send a draft\n"
            "• 'skip Bernard' — skip a draft\n"
            "• 'edit Xia Dan to say...' — update a draft\n"
            "• 'status' — see overview"
        )


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

    # Warm up the brain client so the first real message doesn't pay cold-start cost.
    try:
        from outreach import telegram_brain
        telegram_brain.parse_intent("status", queue_names=[])
        print("Brain warmed up.")
    except Exception as exc:
        print(f"Brain warm-up skipped: {exc}")

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
                dispatch(update)
                offset = update["update_id"] + 1

            if once:
                print(f"Fetched {len(updates)} update(s).")
                break

    except KeyboardInterrupt:
        print("\nPolling stopped.")
