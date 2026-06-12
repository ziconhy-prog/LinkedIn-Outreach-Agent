"""Conversational brain for the Telegram operator bot.

This replaces the old single-shot intent classifier with a proper agent loop:
Claude sees the recent conversation history plus a set of tools (show queue,
redraft, skip, prepare a send, ...) and decides what to do — including asking
follow-up questions it can actually understand the answers to, and doing
several things from one message ("skip Bernard and send Keith").

Safety: the brain can never send anything to LinkedIn. The only send path is
``prepare_send``, which stages a confirmation — telegram_bot then shows Zico
a Send/Cancel button and only a button tap triggers the real send.

If the Claude API is unreachable the bot says so honestly instead of silently
degrading to keyword matching (slash commands in telegram_bot still work
without the API).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

import anthropic

from outreach import audit
from outreach.config import ANTHROPIC_API_KEY
from outreach.db.connection import get_connection

_MODEL = "claude-sonnet-4-6"
_MAX_TOOL_ROUNDS = 8
_MAX_HISTORY_MESSAGES = 24
_MYT = timezone(timedelta(hours=8))

_client: anthropic.Anthropic | None = None

# Per-chat conversation history: chat_id -> list of anthropic message dicts.
_HISTORIES: dict[int, list[dict]] = {}

# Guard so two prospecting runs can't overlap.
_PROSPECTING_LOCK = threading.Lock()


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_STATIC = """\
You are the assistant running Zico's LinkedIn outreach operation, chatting with \
him on Telegram. Zico is a Malaysian startup founder (SkillTrainer AI, practical \
AI workforce training for SMEs). He is NOT technical — talk like a sharp human \
assistant, not like software.

WHAT THE SYSTEM DOES
- Finds prospects from his BNI contact list, researches them on LinkedIn, and
  drafts personalised opener messages.
- Drafts wait in a queue for his approval. NOTHING is sent without his
  explicit confirmation via a button tap.
- A separate automated flow replies to inbound LinkedIn messages and escalates
  tricky ones to him here.
- Meetings get booked into his Google Calendar.

HOW TO BEHAVE
- Use tools for everything. Never claim something was done without calling the
  matching tool, and never invent prospects, drafts, or research.
- Before acting, be sure WHICH draft he means. If only one draft is in the
  queue, assume that one. If it's ambiguous, ask — and list the names so he
  can just reply with one.
- Style/tone/angle/length changes ("make it more casual", "too salesy",
  "shorter", "adjust the tone", "try the cost angle") → use the redraft tool
  with his words as the instruction. Use edit_draft ONLY when he gives the
  literal replacement text.
- Sending: you can never send directly. prepare_send stages it and Zico gets a
  confirm button. After calling it, tell him to tap the button.
- He may ask for several things in one message — do them all.
- If he corrects you ("no, I meant..."), just do the right thing; one short
  acknowledgment, no long apology.
- If a tool returns an error, explain it plainly and say what he can do next.
- When he's unsure what to say, offer 3-4 example phrases.
- Keep replies short and casual. Plain text only — no markdown headings, no
  asterisks. Telegram shows your text verbatim.
"""


def _system_dynamic() -> str:
    """Fresh context injected on every call: date + live queue snapshot."""
    now = datetime.now(_MYT)
    lines = [
        f"Current date/time: {now.strftime('%A %d %B %Y, %H:%M')} (Malaysia, UTC+8).",
    ]
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.id, p.name, m.status
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status IN ('draft', 'edited')
            ORDER BY m.created_at ASC
            LIMIT 15
            """
        ).fetchall()
        active = conn.execute(
            "SELECT count(*) FROM threads WHERE status = 'active'"
        ).fetchone()[0]
    finally:
        conn.close()
    if rows:
        names = ", ".join(f"{r['name']} (draft #{r['id']})" for r in rows)
        lines.append(f"Drafts currently in queue: {names}.")
    else:
        lines.append("Drafts currently in queue: none.")
    lines.append(f"Active LinkedIn conversations: {active}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

_NAME_ARG = {
    "type": "string",
    "description": "Prospect name or fragment as Zico said it (e.g. 'keith', 'Xia Dan'). "
                   "Empty string means 'the only/obvious one'.",
}

TOOLS: list[dict] = [
    {
        "name": "get_queue",
        "description": "List the opener drafts waiting for approval, with their full text.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_status",
        "description": "System overview: drafts waiting, active conversations, recent activity.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_research",
        "description": "Show profile info, research brief, and current draft for one prospect.",
        "input_schema": {
            "type": "object",
            "properties": {"name": _NAME_ARG},
            "required": ["name"],
        },
    },
    {
        "name": "get_skipped",
        "description": "List recently skipped drafts (these can be restored).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "skip_draft",
        "description": "Skip (discard) a draft so it won't be sent. Reversible via restore_draft.",
        "input_schema": {
            "type": "object",
            "properties": {"name": _NAME_ARG},
            "required": ["name"],
        },
    },
    {
        "name": "restore_draft",
        "description": "Bring a previously skipped draft back into the queue.",
        "input_schema": {
            "type": "object",
            "properties": {"name": _NAME_ARG},
            "required": ["name"],
        },
    },
    {
        "name": "edit_draft",
        "description": "Replace a draft's text with EXACT text Zico provided word-for-word. "
                       "For style/tone/angle/length changes use redraft instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": _NAME_ARG,
                "new_text": {"type": "string", "description": "The literal replacement text."},
            },
            "required": ["name", "new_text"],
        },
    },
    {
        "name": "redraft",
        "description": "Have the AI rewrite ONE draft following an instruction (tone, angle, "
                       "length, etc.). Returns the new text — show it to Zico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": _NAME_ARG,
                "instruction": {
                    "type": "string",
                    "description": "What to change, in Zico's words (e.g. 'more casual', "
                                   "'lead with the cost angle', 'shorter').",
                },
            },
            "required": ["name", "instruction"],
        },
    },
    {
        "name": "redraft_all",
        "description": "Rewrite EVERY pending draft with the same instruction. "
                       "Takes a little while; returns a summary with the new texts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "The change to apply to all drafts."},
            },
            "required": ["instruction"],
        },
    },
    {
        "name": "prepare_send",
        "description": "Stage a draft for sending to LinkedIn. Zico will see the draft with a "
                       "Send/Cancel button — the send only happens when he taps Send. "
                       "This is the ONLY way anything reaches LinkedIn.",
        "input_schema": {
            "type": "object",
            "properties": {"name": _NAME_ARG},
            "required": ["name"],
        },
    },
    {
        "name": "start_prospecting",
        "description": "Find new prospects from the BNI list, research them on LinkedIn, and "
                       "draft openers. Runs in the background for several minutes and posts "
                       "progress updates as separate messages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "How many prospects to find (1-5). Default 3.",
                },
            },
        },
    },
    {
        "name": "book_meeting",
        "description": "Create a Google Calendar event for a meeting with a prospect. "
                       "Work out the exact date from today's date if Zico says 'tomorrow' etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prospect_name": {"type": "string", "description": "Prospect name or fragment."},
                "date": {"type": "string", "description": "Meeting date, YYYY-MM-DD."},
                "time": {"type": "string", "description": "Meeting start time, 24h HH:MM."},
                "location": {"type": "string", "description": "Where (e.g. 'Bangsar', 'video call')."},
            },
            "required": ["prospect_name", "date", "time", "location"],
        },
    },
    {
        "name": "health_check",
        "description": "Check system health: database, Claude API, Telegram, Google Calendar, "
                       "and LinkedIn login. The LinkedIn check opens a browser and takes ~20s.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ---------------------------------------------------------------------------
# Draft resolution
# ---------------------------------------------------------------------------

def _fetch_drafts(statuses: tuple[str, ...] = ("draft", "edited")) -> list[dict]:
    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in statuses)
        rows = conn.execute(
            f"""
            SELECT m.id, m.status, m.content, p.id AS prospect_id, p.name,
                   p.company, p.city, p.area, r.brief_md
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            LEFT JOIN research r ON r.prospect_id = p.id
            WHERE m.status IN ({placeholders})
            ORDER BY m.created_at ASC
            """,
            statuses,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _resolve_draft(
    name: str,
    statuses: tuple[str, ...] = ("draft", "edited"),
) -> tuple[dict | None, str | None]:
    """Match a name fragment to exactly one draft. Returns (row, error_message)."""
    rows = _fetch_drafts(statuses)
    label = "skipped drafts" if statuses == ("skipped",) else "drafts in the queue"
    if not rows:
        return None, f"There are no {label} right now."

    frag = (name or "").lower().strip()
    if not frag:
        if len(rows) == 1:
            return rows[0], None
        names = ", ".join(r["name"] for r in rows)
        return None, f"There are {len(rows)} {label}: {names}. Which one does Zico mean?"

    matches = [r for r in rows if frag in r["name"].lower()]
    if not matches:
        frag_tokens = set(frag.split())
        matches = [r for r in rows if frag_tokens & set(r["name"].lower().split())]
    if not matches:
        names = ", ".join(r["name"] for r in rows)
        return None, f"No {label[:-1] if label.endswith('s') else label} matches '{name}'. Available: {names}."
    if len(matches) > 1:
        names = ", ".join(r["name"] for r in matches)
        return None, f"'{name}' matches more than one: {names}. Ask Zico which one."
    return matches[0], None


# ---------------------------------------------------------------------------
# Tool implementations — each returns a plain string for Claude to relay.
# ---------------------------------------------------------------------------

def _tool_get_queue() -> str:
    rows = _fetch_drafts()
    if not rows:
        return "The queue is empty — no drafts waiting."
    parts = [f"{len(rows)} draft(s) waiting:"]
    for r in rows:
        tag = " [edited]" if r["status"] == "edited" else ""
        parts.append(
            f"\n— {r['name']} ({r['company'] or 'company unknown'}){tag}, "
            f"{len(r['content'])} chars:\n{r['content']}"
        )
    return "\n".join(parts)


def _tool_get_status() -> str:
    conn = get_connection()
    try:
        drafts = conn.execute(
            "SELECT count(*) FROM messages WHERE status IN ('draft', 'edited')"
        ).fetchone()[0]
        active = conn.execute(
            "SELECT count(*) FROM threads WHERE status = 'active'"
        ).fetchone()[0]
        sent_today = conn.execute(
            "SELECT count(*) FROM messages WHERE status = 'sent' "
            "AND DATE(sent_at, 'localtime') = DATE('now', 'localtime')"
        ).fetchone()[0]
        attention = conn.execute(
            "SELECT count(*) FROM messages WHERE needs_attention = 1 "
            "AND direction = 'inbound'"
        ).fetchone()[0]
    finally:
        conn.close()
    return (
        f"Drafts awaiting approval: {drafts}\n"
        f"Active LinkedIn conversations: {active}\n"
        f"Messages sent today: {sent_today}\n"
        f"Inbound messages needing Zico's attention: {attention}"
    )


def _tool_get_research(name: str) -> str:
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
            (f"%{(name or '').lower().strip()}%",),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return f"No prospect found matching '{name}'."
    parts = [f"Name: {row['name']}"]
    if row["company"]:
        parts.append(f"Company: {row['company']}")
    if row["profession"]:
        parts.append(f"Role: {row['profession']}")
    location = row["city"] or row["area"] or ""
    if location:
        parts.append(f"Location: {location}")
    if row["category"]:
        parts.append(f"BNI category: {row['category']}")
    if row["linkedin_url"]:
        parts.append(f"LinkedIn: {row['linkedin_url']}")
    if row["brief_md"]:
        parts.append(f"\nResearch brief:\n{row['brief_md']}")
    if row["draft_content"]:
        parts.append(f"\nCurrent draft opener:\n{row['draft_content']}")
    elif row["enrichment_status"] == "pending":
        parts.append("\nNot yet researched — run prospecting to get research and a draft.")
    return "\n".join(parts)


def _tool_get_skipped() -> str:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.id, p.name, m.content
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status = 'skipped'
            ORDER BY m.created_at DESC
            LIMIT 5
            """
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "No skipped drafts."
    return "Recently skipped (restorable): " + ", ".join(r["name"] for r in rows)


def _tool_skip_draft(name: str) -> str:
    row, err = _resolve_draft(name)
    if err:
        return err
    conn = get_connection()
    try:
        conn.execute("UPDATE messages SET status = 'skipped' WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    audit.log("telegram_command", target=f"skip_{row['id']}")
    return f"Skipped the draft for {row['name']}. It can be restored if Zico changes his mind."


def _tool_restore_draft(name: str) -> str:
    row, err = _resolve_draft(name, statuses=("skipped",))
    if err:
        return err
    conn = get_connection()
    try:
        conn.execute("UPDATE messages SET status = 'draft' WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()
    audit.log("telegram_command", target=f"restore_{row['id']}")
    return f"Restored the draft for {row['name']} — it's back in the queue."


def _tool_edit_draft(name: str, new_text: str) -> str:
    if not new_text.strip():
        return "No replacement text given — ask Zico what the draft should say."
    row, err = _resolve_draft(name)
    if err:
        return err
    text = new_text.strip()
    if len(text) > 300:
        return (
            f"That text is {len(text)} characters — LinkedIn connection notes cap at 300, "
            "so the send would fail. Ask Zico to shorten it, or offer to shorten it for him."
        )
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE messages SET content = ?, status = 'edited' WHERE id = ?",
            (text, row["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    audit.log("telegram_command", target=f"edit_{row['id']}")
    return f"Updated {row['name']}'s draft ({len(text)} chars). New text:\n{text}"


def _tool_redraft(name: str, instruction: str) -> str:
    if not instruction.strip():
        return "No direction given — ask Zico what he wants changed."
    row, err = _resolve_draft(name)
    if err:
        return err
    if not row["brief_md"]:
        return (
            f"{row['name']} has no research brief, so the AI can't redraft safely. "
            "Zico can edit the text directly instead."
        )
    from outreach import drafter

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
        return f"Redraft failed ({type(exc).__name__}: {exc}). Try again in a minute."

    if len(new_text) > 300:
        return (
            f"The rewrite came out at {len(new_text)} chars — over the 300-char LinkedIn "
            "limit, so it was NOT saved. Retry the redraft tool with the same instruction "
            "plus 'keep it under 280 characters'."
        )

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
    audit.log("telegram_command", target=f"redraft_{row['id']}")
    return f"New draft for {row['name']} ({len(new_text)} chars) — show it to Zico:\n{new_text}"


def _tool_redraft_all(instruction: str) -> str:
    if not instruction.strip():
        return "No direction given — ask Zico what style/angle to apply to all drafts."
    rows = _fetch_drafts()
    if not rows:
        return "The queue is empty — nothing to redraft."
    results = []
    for row in rows:
        results.append(_tool_redraft(row["name"], instruction))
    return "\n\n".join(results)


def _tool_prepare_send(name: str, staged: list[dict]) -> str:
    row, err = _resolve_draft(name)
    if err:
        return err
    staged.append({"message_id": row["id"], "name": row["name"]})
    return (
        f"Staged. Zico will now see {row['name']}'s draft with a Send/Cancel button — "
        "tell him to tap Send to fire it. Nothing is sent until he does."
    )


def _tool_start_prospecting(count: int, chat_id: int) -> str:
    limit = max(1, min(int(count or 3), 5))
    if not _PROSPECTING_LOCK.acquire(blocking=False):
        return "A prospecting run is already in progress — wait for it to finish first."

    from outreach import prospecting_pipeline
    from outreach.telegram_client import send_message as _send

    def _notify(msg: str) -> None:
        try:
            _send(chat_id, msg)
        except Exception:  # noqa: BLE001
            pass

    def _run() -> None:
        try:
            prospecting_pipeline.run(limit=limit, notify=_notify)
        except Exception as exc:  # noqa: BLE001
            _notify(f"⚠️ Prospecting stopped with an error: {exc}")
        finally:
            _PROSPECTING_LOCK.release()

    threading.Thread(target=_run, daemon=True).start()
    return (
        f"Prospecting started in the background for {limit} prospect(s). "
        "Progress updates will arrive as separate messages over the next few minutes."
    )


def _tool_book_meeting(prospect_name: str, date: str, time_s: str, location: str) -> str:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, company, linkedin_url FROM prospects "
            "WHERE lower(name) LIKE ? LIMIT 1",
            (f"%{prospect_name.lower().strip()}%",),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return f"No prospect found matching '{prospect_name}'."

    try:
        start = datetime.strptime(f"{date} {time_s}", "%Y-%m-%d %H:%M").replace(tzinfo=_MYT)
    except ValueError:
        return f"Couldn't understand the date/time ('{date} {time_s}'). Ask Zico to re-confirm."
    if start < datetime.now(_MYT):
        return f"That time ({start.strftime('%A %d %B, %I:%M%p')}) is in the past — ask Zico to re-confirm."

    from outreach import calendar_client

    try:
        end = start + timedelta(hours=1)
        if not calendar_client.is_free(start, end):
            return (
                f"Zico's calendar already has something at "
                f"{start.strftime('%A %d %B, %I:%M%p')}. Ask if he wants to double-book."
            )
        event_url = calendar_client.create_meeting_event(
            prospect_name=row["name"],
            company=row["company"] or "",
            linkedin_url=row["linkedin_url"] or "",
            start=start,
            location=location,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f"Calendar booking failed: {exc}. "
            "If the calendar isn't connected yet, run connect-calendar on the Mac once."
        )
    audit.log("meeting_booked", target=f"prospect:{row['id']}")
    return (
        f"Booked: {row['name']} ({row['company'] or 'company unknown'}), "
        f"{start.strftime('%A %d %B, %I:%M%p')} at {location}. Event: {event_url}"
    )


def _tool_health_check() -> str:
    from outreach.config import (
        DATA_DIR,
        TELEGRAM_BOT_TOKEN,
        TELEGRAM_OPERATOR_USER_ID,
    )
    import os

    lines = []

    # Telegram — if we're answering, it works.
    if TELEGRAM_BOT_TOKEN and TELEGRAM_OPERATOR_USER_ID:
        lines.append("✅ Telegram: connected (you're chatting through it now)")
    else:
        lines.append("❌ Telegram: bot token or operator ID missing in .env")

    # Claude API — this very reply proves it.
    lines.append("✅ Claude AI: working (this reply came from it)")

    # Database.
    try:
        conn = get_connection()
        try:
            n = conn.execute("SELECT count(*) FROM prospects").fetchone()[0]
        finally:
            conn.close()
        lines.append(f"✅ Database: OK ({n} prospects loaded)")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"❌ Database: problem — {exc}")

    # Google Calendar token.
    token_path = os.getenv("GOOGLE_OAUTH_TOKEN_PATH", "").strip() or str(
        DATA_DIR / "google_oauth_token.json"
    )
    if os.path.exists(token_path):
        lines.append("✅ Google Calendar: connected")
    else:
        lines.append(
            "⚠️ Google Calendar: not connected yet — run connect-calendar once on the Mac"
        )

    # LinkedIn session (slow — opens a browser).
    try:
        from outreach.linkedin.session import check_session

        if check_session():
            lines.append("✅ LinkedIn: logged in")
        else:
            lines.append(
                "❌ LinkedIn: session expired — open the bot's browser and log in again "
                "(linkedin-login on the Mac)"
            )
    except Exception as exc:  # noqa: BLE001
        lines.append(f"⚠️ LinkedIn: couldn't check ({exc})")

    return "\n".join(lines)


# Registry — the live-eval script patches this to spy on tool choices.
TOOL_IMPLS: dict = {
    "get_queue": lambda args, ctx: _tool_get_queue(),
    "get_status": lambda args, ctx: _tool_get_status(),
    "get_research": lambda args, ctx: _tool_get_research(args.get("name", "")),
    "get_skipped": lambda args, ctx: _tool_get_skipped(),
    "skip_draft": lambda args, ctx: _tool_skip_draft(args.get("name", "")),
    "restore_draft": lambda args, ctx: _tool_restore_draft(args.get("name", "")),
    "edit_draft": lambda args, ctx: _tool_edit_draft(
        args.get("name", ""), args.get("new_text", "")
    ),
    "redraft": lambda args, ctx: _tool_redraft(
        args.get("name", ""), args.get("instruction", "")
    ),
    "redraft_all": lambda args, ctx: _tool_redraft_all(args.get("instruction", "")),
    "prepare_send": lambda args, ctx: _tool_prepare_send(
        args.get("name", ""), ctx["staged_sends"]
    ),
    "start_prospecting": lambda args, ctx: _tool_start_prospecting(
        args.get("count", 3), ctx["chat_id"]
    ),
    "book_meeting": lambda args, ctx: _tool_book_meeting(
        args.get("prospect_name", ""),
        args.get("date", ""),
        args.get("time", ""),
        args.get("location", ""),
    ),
    "health_check": lambda args, ctx: _tool_health_check(),
}


def _execute_tool(name: str, args: dict, ctx: dict) -> str:
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        return f"Unknown tool '{name}'."
    try:
        return impl(args, ctx)
    except Exception as exc:  # noqa: BLE001
        return f"Tool '{name}' failed ({type(exc).__name__}: {exc})."


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

def _serialize_content(blocks) -> list[dict]:
    out = []
    for b in blocks:
        if b.type == "text":
            out.append({"type": "text", "text": b.text})
        elif b.type == "tool_use":
            out.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
    return out


def _trim_history(messages: list[dict]) -> list[dict]:
    """Cap history length; ensure it starts with a plain user text message."""
    trimmed = messages[-_MAX_HISTORY_MESSAGES:]
    while trimmed:
        first = trimmed[0]
        if first["role"] == "user" and isinstance(first.get("content"), str):
            break
        trimmed.pop(0)
    return trimmed


def handle_message(chat_id: int, text: str) -> dict:
    """Run one conversational turn. Returns {'reply': str, 'staged_sends': [...]}.

    staged_sends entries are {'message_id': int, 'name': str} — telegram_bot
    shows a Send/Cancel button for each.
    """
    if not ANTHROPIC_API_KEY:
        return {
            "reply": (
                "⚠️ My AI brain isn't configured (ANTHROPIC_API_KEY is missing in .env). "
                "Slash commands like /queue and /skip still work."
            ),
            "staged_sends": [],
        }

    history = _HISTORIES.get(chat_id, [])
    messages = history + [{"role": "user", "content": text}]
    ctx = {"chat_id": chat_id, "staged_sends": []}

    client = _get_client()
    system = [
        {"type": "text", "text": _SYSTEM_STATIC, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": _system_dynamic()},
    ]

    final_text = ""
    try:
        for _ in range(_MAX_TOOL_ROUNDS):
            response = client.messages.create(
                model=_MODEL,
                max_tokens=1000,
                temperature=0.3,
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            content = _serialize_content(response.content)
            messages.append({"role": "assistant", "content": content})
            final_text = "\n".join(
                b["text"] for b in content if b["type"] == "text"
            ).strip()

            if response.stop_reason != "tool_use":
                break

            results = []
            for block in content:
                if block["type"] == "tool_use":
                    print(f"[brain] tool={block['name']} input={block['input']}")
                    output = _execute_tool(block["name"], block["input"], ctx)
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": output,
                        }
                    )
            messages.append({"role": "user", "content": results})
    except anthropic.APIError as exc:
        return {
            "reply": (
                "⚠️ I'm having trouble reaching my AI brain right now "
                f"({type(exc).__name__}). Give it a minute and try again — "
                "or use /queue and /skip which work without it."
            ),
            "staged_sends": [],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "reply": f"⚠️ Something went wrong on my side ({type(exc).__name__}: {exc}). Try again.",
            "staged_sends": [],
        }

    _HISTORIES[chat_id] = _trim_history(messages)
    return {"reply": final_text, "staged_sends": ctx["staged_sends"]}


def reset_history(chat_id: int) -> None:
    """Forget the conversation (used by /reset)."""
    _HISTORIES.pop(chat_id, None)
