"""Claude API-powered intent router for the Telegram operator bot.

Replaces keyword-based _detect_intent() with an LLM that understands
natural language, extracts prospect names, and resolves ambiguous phrasing.

Called once per Telegram message. Uses Haiku for low latency and cost.
"""

from __future__ import annotations

import json
import re

import anthropic

from outreach.config import ANTHROPIC_API_KEY
from outreach.db.connection import get_connection

_SYSTEM = """\
You are the intent router for Zico's LinkedIn outreach Telegram bot.
Zico is a Malaysian startup founder managing cold LinkedIn outreach to BNI prospects.

Parse Zico's message into a JSON action. Output ONLY the JSON object — no markdown, no explanation.

The bot has full access to a BNI prospect list (700+ contacts). It can search LinkedIn,
scrape profiles, draft openers, send messages, and book meetings. NEVER claim the bot
lacks a capability it has. When in doubt, use clarify — not chat.

Available actions:
  show_queue        — show pending drafts awaiting approval
  show_status       — system overview (thread count, draft count)
  send_draft        — approve and send a draft to LinkedIn
  skip_draft        — skip/delete a draft
  restore_draft     — bring back a previously skipped draft (target_name = prospect name)
                      (also: "bring back X", "undelete X", "restore X", "put X back",
                       "actually keep X", "I changed my mind about X")
  edit_draft        — replace draft text with new text
  redraft           — request AI redraft of ONE draft, with a direction/instruction
  redraft_all       — request AI redraft of EVERY pending draft at once, with the
                      same instruction applied to all (also: "redraft all", "redraft
                      everything", "redo all the drafts", "fix all the drafts").
                      The instruction must capture the style/angle change to apply.
  book_meeting      — book a Google Calendar event
  start_prospecting — search the BNI list, find LinkedIn profiles, and draft openers
                      (also: "try a different person", "find another one", "scrape the BNI list",
                       "yes find him and create a draft", "find him and draft", "search BNI",
                       "get me new leads", "pull from BNI", "find another prospect")
  show_research     — show profile info and research for a prospect
                      (also: "tell me about X", "what does X do", "who is X",
                       "what's X's company", "details on X", "info on X")
  help              — show help text
  clarify           — not enough info; set reply = a short specific question to ask Zico
  chat              — ONLY for genuine small talk with no action needed (set reply = casual response)
                      Do NOT use chat when an action could apply.

JSON schema (always output all fields, even if empty):
{
  "intent": "<action name>",
  "target_name": "<prospect name fragment as Zico typed it, or empty string>",
  "find_replacement": false,
  "new_text": "",
  "instruction": "",
  "reply": ""
}

Field rules:
- target_name: MUST be set to the name fragment Zico typed if ANY name
  appears in the message. Examples:
    "send adibah" → target_name="adibah"
    "send keith ngai" → target_name="keith ngai"
    "approve KC" → target_name="KC"
    "skip Bernard" → target_name="Bernard"
  Use target_name="" ONLY when the message contains NO name at all
  (e.g. "send it", "go ahead", "approve"). Even if just one draft is in the
  queue, you still extract the name if Zico typed one.
- send_draft RULE: fire send_draft IF AND ONLY IF the message contains one of these
  send verbs: "send", "approve", "ship", "fire", "blast", "shoot", "dispatch".
  If a send verb is present → intent=send_draft (e.g. "send it", "approve KC",
  "send Keith", "ship Bernard", "fire it off" — all fire send_draft).
  If NO send verb is present → never fire send_draft, even if the message sounds
  affirmative. Bare words like "yes", "ok", "go ahead", "looks good", "sounds good",
  "alright", "yep", "sure" → intent=clarify with
  reply="Want me to send it? Say 'send [name]' or 'send it'."
- send_draft with no name: target_name = "" (means "send the last one shown")
- skip_draft: find_replacement = true only if Zico explicitly asks for a new/replacement prospect
- edit_draft: new_text must be non-empty; if no replacement text is given, use clarify
- redraft: instruction = what Zico wants changed (e.g. "make it shorter", "try the cost angle")
- redraft_all: instruction = the style/angle change to apply to every draft
  (e.g. "use the warm-connect 3-part structure under 300 chars"). target_name MUST be empty.
- book_meeting: instruction = the full booking string (name, date, time, location)
- chat: keep reply short and casual — Zico is Malaysian, friendly tone
- clarify: reply = a short, specific question to ask Zico
"""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _fetch_queue_names() -> list[dict]:
    """Return id + name for drafts currently in queue."""
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
            LIMIT 10
            """
        ).fetchall()
        return [{"id": r["id"], "name": r["name"]} for r in rows]
    finally:
        conn.close()


def parse_intent(
    message: str,
    queue_names: list[dict] | None = None,
) -> dict:
    """Parse a natural language Telegram message into a structured action dict.

    Args:
        message: Raw text from Zico's Telegram message.
        queue_names: Optional pre-fetched list of {id, name} dicts for context.
                     Fetched from DB automatically if not provided.

    Returns:
        Dict with keys: intent, target_name, find_replacement, new_text, instruction, reply.
        Falls back to keyword detection if API key is missing or call fails.
    """
    if not ANTHROPIC_API_KEY:
        return _fallback(message)

    if queue_names is None:
        queue_names = _fetch_queue_names()

    if queue_names:
        queue_ctx = "Drafts in queue: " + ", ".join(
            f"{r['name']} (#{r['id']})" for r in queue_names
        )
    else:
        queue_ctx = "Drafts in queue: none"

    user_content = f"{queue_ctx}\n\nZico says: {message}"

    try:
        client = _get_client()
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
    except Exception:
        return _fallback(message)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                return _fallback(message)
        else:
            return _fallback(message)

    return {
        "intent": result.get("intent") or "clarify",
        "target_name": result.get("target_name") or "",
        "find_replacement": bool(result.get("find_replacement", False)),
        "new_text": result.get("new_text") or "",
        "instruction": result.get("instruction") or "",
        "reply": result.get("reply") or "",
    }


_TRIGGER_WORDS = {
    "send", "approve", "ship", "fire", "blast", "shoot", "dispatch",
    "skip", "delete", "remove", "drop", "discard", "scrap",
    "edit", "change", "rewrite", "replace", "tweak", "fix", "adjust",
    "bring", "back", "restore", "undelete", "keep",
    "tell", "about", "show", "details", "info", "research",
    "the", "a", "to", "for", "me", "please", "this", "that", "it",
    "message", "draft", "one", "guy", "person", "prospect",
}


def _extract_name_fallback(message: str) -> str:
    """Strip trigger words and return remaining text as a name fragment."""
    tokens = [t.strip(",.!?'\"") for t in message.split()]
    keep = [t for t in tokens if t and t.lower() not in _TRIGGER_WORDS]
    return " ".join(keep).strip()


def _fallback(message: str) -> dict:
    """Keyword-based fallback when API is unavailable."""
    lower = message.lower()
    words = set(lower.split())

    intent = "clarify"
    if any(p in lower for p in ("run a search", "find prospects", "pull prospects", "start prospecting", "find new leads", "new prospects")):
        intent = "start_prospecting"
    elif any(p in lower for p in ("booked", "meeting confirmed", "confirmed meeting", "scheduled")):
        intent = "book_meeting"
    elif any(p in lower for p in ("bring back", "put back", "restore", "undelete")):
        intent = "restore_draft"
    elif words & {"skip", "delete", "remove", "drop", "discard", "scrap"}:
        intent = "skip_draft"
    elif words & {"edit", "change", "rewrite", "replace", "tweak", "fix", "adjust"}:
        intent = "edit_draft"
    elif words & {"send", "approve", "ship", "fire", "blast", "shoot", "dispatch"}:
        intent = "send_draft"
    elif any(p in lower for p in ("tell me about", "what does", "who is", "details on", "info on", "show me")):
        intent = "show_research"
    elif words & {"queue", "drafts", "pending", "waiting", "list"}:
        intent = "show_queue"
    elif words & {"status", "start", "summary", "overview", "report"}:
        intent = "show_status"
    elif words & {"help", "commands", "options"}:
        intent = "help"

    # Extract a name fragment for actions that need it.
    target_name = ""
    if intent in ("send_draft", "skip_draft", "edit_draft", "restore_draft", "show_research", "redraft"):
        target_name = _extract_name_fallback(message)

    return {
        "intent": intent,
        "target_name": target_name,
        "find_replacement": any(p in lower for p in ("find another", "find a new", "new prospect", "replace")),
        "new_text": "",
        "instruction": message if intent == "book_meeting" else "",
        "reply": "Not sure what you mean. Try 'show queue', 'send [name]', or 'status'.",
    }
