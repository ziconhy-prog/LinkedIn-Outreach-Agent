"""Orchestrate one inbox cycle: poll → classify → draft → send or escalate.

Flow:
  1. Fetch active threads with LinkedIn URLs from DB.
  2. Poll LinkedIn inbox for new inbound messages.
  3. For each new message:
     a. Store it as an inbound message row.
     b. Classify (normal / pricing / not_interested / aggressive / meeting_request).
     c. Escalate: set needs_attention, notify Telegram, skip auto-draft.
     d. Normal: draft reply via Claude API, store as auto_draft, wait humanlike
        delay, send via Playwright, mark sent.

Only the opener requires Telegram approval. All subsequent normal replies are
sent automatically. Edge cases always escalate to Zico.
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone

from outreach import audit, calendar_client, classifier, drafter, meeting_extractor
from outreach.db.connection import get_connection
from outreach.linkedin.inbox import poll_inbox
from outreach.linkedin.send import SendError, send_message
from outreach.linkedin.session import check_session
from outreach.telegram_client import send_operator_message as telegram_notify


# Humanlike delay range in seconds before auto-sending (15–45 minutes).
_DELAY_MIN_S = 15 * 60
_DELAY_MAX_S = 45 * 60


def _fetch_active_threads() -> list[dict]:
    """Return threads that are active and have a LinkedIn URL to poll."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT t.id AS thread_id, t.prospect_id, t.outbound_count,
                   t.last_inbound_at, t.pending_meeting_at,
                   p.name AS prospect_name, p.company, p.category,
                   p.linkedin_url
            FROM threads t
            JOIN prospects p ON t.prospect_id = p.id
            WHERE t.status = 'active'
              AND p.linkedin_url IS NOT NULL
              AND p.do_not_contact = 0
            """
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _fetch_research(prospect_id: int) -> tuple[str, list[dict]]:
    """Return (brief_md, conversation_history) for a prospect."""
    conn = get_connection()
    try:
        research = conn.execute(
            "SELECT brief_md FROM research WHERE prospect_id = ?",
            (prospect_id,),
        ).fetchone()
        brief = (research["brief_md"] or "") if research else ""

        history_rows = conn.execute(
            """
            SELECT m.direction, m.content
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            WHERE t.prospect_id = ?
              AND m.status IN ('sent', 'auto_draft')
            ORDER BY m.created_at ASC
            """,
            (prospect_id,),
        ).fetchall()
        history = [dict(r) for r in history_rows]

        return brief, history
    finally:
        conn.close()


def _store_inbound(thread_id: int, content: str) -> int:
    """Store an inbound message and return its ID."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO messages (thread_id, direction, role, content, status)
            VALUES (?, 'inbound', 'reply', ?, 'received')
            """,
            (thread_id, content),
        )
        conn.execute(
            "UPDATE threads SET last_inbound_at = CURRENT_TIMESTAMP, "
            "inbound_count = inbound_count + 1 WHERE id = ?",
            (thread_id,),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _store_auto_draft(thread_id: int, content: str) -> int:
    """Store an auto-drafted outbound reply and return its ID."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO messages
                (thread_id, direction, role, content, status, approved_via)
            VALUES (?, 'outbound', 'reply', ?, 'auto_draft', 'auto')
            """,
            (thread_id, content),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _escalate(thread_id: int, inbound_id: int, reason: str, content: str) -> None:
    """Flag inbound message as needing attention and notify Telegram."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE messages
            SET needs_attention = 1, needs_attention_reason = ?
            WHERE id = ?
            """,
            (reason, inbound_id),
        )
        conn.execute(
            "UPDATE threads SET status = 'active' WHERE id = ?",
            (thread_id,),
        )
        conn.commit()
    finally:
        conn.close()

    audit.log("inbox_escalate", target=f"thread:{thread_id}", success=True)

    # Notify Telegram.
    preview = content[:200].replace("\n", " ")
    label = {
        "pricing": "Pricing question",
        "not_interested": "Not interested",
        "aggressive": "Aggressive reply",
        "meeting_request": "Meeting request",
        "architecture_question": "Architecture / tech question — reply manually",
        "uncertain": "Uncertain — needs your review",
    }.get(reason, reason)

    try:
        telegram_notify(
            f"⚠️ NEEDS YOU — {label}\n\nThread {thread_id}:\n\"{preview}\"\n\n"
            f"Run /queue to review.",
        )
    except Exception:  # noqa: BLE001
        pass  # Telegram notify failure shouldn't block inbox processing.


def _handle_meeting_confirmed(
    thread_id: int,
    inbound_id: int,
    msg: dict,
    thread_info: dict,
) -> None:
    """Ask for meeting location, then book once prospect replies with it."""
    import random as _random
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    _myt = _tz(_td(hours=8))

    # Extract date/time or default to 2-3 days out at 2PM.
    details = meeting_extractor.extract_meeting_details(msg["content"])
    start_dt = meeting_extractor.build_meeting_datetime(details) if details else None

    if not start_dt:
        days_ahead = _random.randint(2, 3)
        now = _dt.now(_myt)
        start_dt = now.replace(hour=14, minute=0, second=0, microsecond=0) + _td(days=days_ahead)
        while start_dt.weekday() >= 5:
            start_dt += _td(days=1)

    # Store the tentative meeting datetime on the thread.
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE threads SET pending_meeting_at = ? WHERE id = ?",
            (start_dt.isoformat(), thread_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Send a location question via LinkedIn.
    location_question = "Sounds good! Where works best for you — happy to come to you or pick somewhere easy."
    draft_id = _store_auto_draft(thread_id, location_question)
    try:
        send_message(draft_id)
    except SendError as exc:
        audit.log("meeting_location_ask_failed", target=f"thread:{thread_id}", success=False, error_message=str(exc))


def _book_meeting_with_location(
    thread_id: int,
    location: str,
    thread_info: dict,
    pending_meeting_at: str,
) -> None:
    """Book the calendar event now that we have the location."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _myt = _tz(_td(hours=8))

    prospect_name = thread_info["prospect_name"]
    company = thread_info.get("company", "")
    linkedin_url = thread_info.get("linkedin_url", "")

    try:
        start_dt = _dt.fromisoformat(pending_meeting_at)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=_myt)
    except Exception:  # noqa: BLE001
        return

    try:
        event_url = calendar_client.create_meeting_event(
            prospect_name=prospect_name,
            company=company,
            linkedin_url=linkedin_url,
            start=start_dt,
            location=location,
        )
        audit.log("meeting_booked", target=f"prospect:{thread_info['prospect_id']}", success=True)

        # Clear pending state.
        conn = get_connection()
        try:
            conn.execute("UPDATE threads SET pending_meeting_at = NULL WHERE id = ?", (thread_id,))
            conn.commit()
        finally:
            conn.close()

        time_str = start_dt.strftime("%A %d %B, %I:%M%p MYT")
        telegram_notify(
            f"📅 Meeting booked!\n\n"
            f"{prospect_name} — {company}\n"
            f"{time_str}\n"
            f"Location: {location}\n"
            f"Calendar: {event_url}"
        )
    except Exception as exc:  # noqa: BLE001
        telegram_notify(
            f"⚠️ Couldn't book {prospect_name}'s meeting: {exc}\n"
            f"Location given: {location}\nPlease book manually."
        )


def run_inbox_cycle(dry_run: bool = False) -> dict:
    """Run one complete inbox cycle. Returns a summary dict."""
    summary = {
        "threads_checked": 0,
        "new_messages": 0,
        "escalated": 0,
        "drafted": 0,
        "sent": 0,
        "errors": 0,
    }

    # Session health check — abort if LinkedIn session is not logged in.
    if not check_session():
        print("❌ LinkedIn session is not active. Run `linkedin-login` to restore it.")
        try:
            telegram_notify(
                "⚠️ poll-inbox aborted: LinkedIn session expired. "
                "Run `linkedin-login` on your Mac to restore it."
            )
        except Exception:  # noqa: BLE001
            pass
        return summary

    active_threads = _fetch_active_threads()
    summary["threads_checked"] = len(active_threads)

    if not active_threads:
        return summary

    new_messages = poll_inbox(active_threads)
    summary["new_messages"] = len(new_messages)

    # Build a map for quick prospect lookup.
    thread_map = {t["thread_id"]: t for t in active_threads}

    for msg in new_messages:
        thread_id = msg["thread_id"]
        thread_info = thread_map.get(thread_id)
        if not thread_info:
            continue

        prospect_id = msg["prospect_id"]

        # Store the inbound message.
        inbound_id = _store_inbound(thread_id, msg["content"])

        # If thread is waiting for a location, treat this reply as the location.
        if thread_info.get("pending_meeting_at"):
            location = msg["content"].strip()
            _book_meeting_with_location(thread_id, location, thread_info, thread_info["pending_meeting_at"])
            summary["escalated"] += 1
            print(f"  ↳ Booked meeting for {thread_info['prospect_name']} at: {location}")
            continue

        # Classify.
        classification = classifier.classify(msg["content"])

        if classification == "meeting_confirmed":
            _handle_meeting_confirmed(thread_id, inbound_id, msg, thread_info)
            summary["escalated"] += 1
            continue

        if classification != "normal":
            reason = classifier.ESCALATION_REASONS.get(classification, classification)
            if not dry_run:
                _escalate(thread_id, inbound_id, reason, msg["content"])
            summary["escalated"] += 1
            print(
                f"  ↳ Escalated thread {thread_id} ({thread_info['prospect_name']}): {reason}"
            )
            continue

        # Draft a reply.
        brief, history = _fetch_research(prospect_id)

        # Include the new inbound in history for context.
        history.append({"direction": "inbound", "content": msg["content"]})

        prospect_dict = {
            "name": thread_info["prospect_name"],
            "company": thread_info["company"],
            "category": thread_info["category"],
        }

        try:
            reply_text = drafter.draft_reply(
                prospect=prospect_dict,
                research_brief=brief,
                conversation_history=history,
                outbound_count=thread_info["outbound_count"],
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ↳ Draft failed for thread {thread_id}: {exc}")
            _escalate(thread_id, inbound_id, "uncertain", msg["content"])
            summary["errors"] += 1
            continue

        # If the drafter signals an escalation, route it — even if the model
        # added preamble before the ESCALATE: token. The signal anywhere in
        # the response counts (safer than allowing a guessed reply to send).
        if "ESCALATE:" in reply_text:
            after = reply_text.split("ESCALATE:", 1)[1].strip()
            # Reason is the first whitespace/punctuation-delimited token.
            reason = after.split()[0].rstrip(".,!?:;\n").lower() if after else "uncertain"
            _escalate(thread_id, inbound_id, reason, msg["content"])
            summary["escalated"] += 1
            print(f"  ↳ Drafter escalated thread {thread_id}: {reason}")
            continue

        summary["drafted"] += 1
        print(f"  ↳ Drafted reply for {thread_info['prospect_name']}:\n    {reply_text[:120]}…")

        if dry_run:
            continue

        # Store draft.
        draft_id = _store_auto_draft(thread_id, reply_text)

        # Humanlike delay.
        delay = random.randint(_DELAY_MIN_S, _DELAY_MAX_S)
        print(f"  ↳ Waiting {delay // 60}m before sending…")
        time.sleep(delay)

        # Send.
        try:
            send_message(draft_id)
            summary["sent"] += 1
            print(f"  ↳ Sent message {draft_id}.")
        except SendError as exc:
            print(f"  ↳ Send failed for message {draft_id}: {exc}")
            audit.log(
                "inbox_send_error",
                target=f"message:{draft_id}",
                success=False,
                error_message=str(exc),
            )
            summary["errors"] += 1

    return summary
