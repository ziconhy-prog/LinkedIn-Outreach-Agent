"""Orchestrate one inbox cycle: poll → classify → draft → send or escalate.

Flow:
  1. Fetch active threads with LinkedIn URLs from DB.
  2. Poll LinkedIn inbox for new inbound messages.
  3. For each new message:
     a. Store it as an inbound message row.
     b. Classify (normal / pricing / not_interested / aggressive / meeting_request).
     c. Escalate: set needs_attention, notify Telegram, skip auto-draft.
     d. Normal: draft reply via Claude API, store as auto_draft with a
        humanlike ``send_after`` delay, then send via Playwright once due.

Auto-replies are scheduled (messages.send_after) rather than slept on, so the
cycle never blocks for long and replies left over from a crashed/expired run
are sent at the start of the next one. A lock file prevents overlapping cycles
from double-sending.

Only the opener requires Telegram approval. All subsequent normal replies are
sent automatically. Edge cases always escalate to Zico.
"""

from __future__ import annotations

import os
import random
import time
from datetime import datetime, timedelta, timezone

from outreach import audit, calendar_client, classifier, drafter, meeting_extractor
from outreach.config import DATA_DIR
from outreach.db.connection import get_connection
from outreach.linkedin.inbox import poll_inbox
from outreach.linkedin.send import SendError, send_message
from outreach.linkedin.session import check_session
from outreach.telegram_client import send_operator_message as telegram_notify


# Humanlike delay range in seconds before auto-sending a drafted reply.
_DELAY_MIN_S = 4 * 60
_DELAY_MAX_S = 12 * 60

# How long the end-of-cycle flush waits for scheduled replies before leaving
# the rest to the next cycle.
_FLUSH_MAX_WAIT_S = 15 * 60

_LOCK_PATH = DATA_DIR / "poll_inbox.lock"
_LOCK_STALE_S = 45 * 60


def _acquire_lock() -> bool:
    """Best-effort cross-platform lock so two cycles can't run at once."""
    try:
        if _LOCK_PATH.exists():
            age = time.time() - _LOCK_PATH.stat().st_mtime
            if age < _LOCK_STALE_S:
                return False
            _LOCK_PATH.unlink()  # stale lock from a crashed run
        fd = os.open(str(_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except (FileExistsError, OSError):
        return False


def _release_lock() -> None:
    try:
        _LOCK_PATH.unlink()
    except OSError:
        pass


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


def _store_auto_draft(thread_id: int, content: str, delay_s: int = 0) -> int:
    """Store an auto-drafted outbound reply and return its ID.

    ``delay_s`` > 0 schedules the send for later (humanlike delay) via the
    ``send_after`` column; 0 means due immediately.
    """
    send_after = (datetime.now(timezone.utc) + timedelta(seconds=delay_s)).isoformat()
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO messages
                (thread_id, direction, role, content, status, approved_via, send_after)
            VALUES (?, 'outbound', 'reply', ?, 'auto_draft', 'auto', ?)
            """,
            (thread_id, content, send_after),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _send_due_replies(summary: dict) -> int:
    """Send every auto_draft whose scheduled time has passed.

    Each message is claimed atomically (auto_draft → approved) before the
    browser send, so even overlapping processes can't double-send. Returns
    how many auto_drafts are still waiting on their schedule.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        due = conn.execute(
            "SELECT id FROM messages WHERE status = 'auto_draft' "
            "AND (send_after IS NULL OR send_after <= ?)",
            (now_iso,),
        ).fetchall()
        remaining = conn.execute(
            "SELECT count(*) FROM messages WHERE status = 'auto_draft' "
            "AND send_after > ?",
            (now_iso,),
        ).fetchone()[0]
    finally:
        conn.close()

    for row in due:
        msg_id = row["id"]
        conn = get_connection()
        try:
            cur = conn.execute(
                "UPDATE messages SET status = 'approved', "
                "approved_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'auto_draft'",
                (msg_id,),
            )
            conn.commit()
            claimed = cur.rowcount > 0
        finally:
            conn.close()
        if not claimed:
            continue  # another process got it first

        try:
            send_message(msg_id)
            summary["sent"] += 1
            print(f"  ↳ Sent scheduled reply {msg_id}.")
        except SendError as exc:
            print(f"  ↳ Send failed for message {msg_id}: {exc}")
            audit.log(
                "inbox_send_error",
                target=f"message:{msg_id}",
                success=False,
                error_message=str(exc),
            )
            summary["errors"] += 1
            # Put it back on the schedule (1h later) so the next cycle retries.
            retry_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE messages SET status = 'auto_draft', send_after = ? "
                    "WHERE id = ? AND status = 'approved'",
                    (retry_at, msg_id),
                )
                conn.commit()
            finally:
                conn.close()
            _notify_operator(
                f"⚠️ A scheduled LinkedIn reply (message {msg_id}) failed to send: {exc}\n"
                "I'll retry in about an hour."
            )

    return remaining


def _notify_operator(text: str) -> None:
    """Telegram-notify the operator; log (never raise) if Telegram is down."""
    try:
        telegram_notify(text)
    except Exception as exc:  # noqa: BLE001
        audit.log(
            "telegram_notify_failed",
            target="operator",
            success=False,
            error_message=str(exc),
        )


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
        "meeting_location_unclear": "Meeting to book — couldn't read the location",
        "uncertain": "Uncertain — needs your review",
    }.get(reason, reason)

    _notify_operator(
        f"⚠️ NEEDS YOU — {label}\n\nThread {thread_id}:\n\"{preview}\"\n\n"
        f"Reply on LinkedIn directly, or ask me about this prospect here.",
    )


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
        _notify_operator(
            f"📅 Meeting booked!\n\n"
            f"{prospect_name} — {company}\n"
            f"{time_str}\n"
            f"Location: {location}\n"
            f"Calendar: {event_url}"
        )
    except Exception as exc:  # noqa: BLE001
        _notify_operator(
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

    if not dry_run and not _acquire_lock():
        print("Another poll-inbox run is already in progress — skipping this one.")
        return summary

    try:
        return _run_inbox_cycle_locked(summary, dry_run)
    finally:
        if not dry_run:
            _release_lock()


def _run_inbox_cycle_locked(summary: dict, dry_run: bool) -> dict:
    # Session health check — abort if LinkedIn session is not logged in.
    if not check_session():
        print("❌ LinkedIn session is not active. Run `linkedin-login` to restore it.")
        _notify_operator(
            "⚠️ poll-inbox aborted: LinkedIn session expired. "
            "Run `linkedin-login` on your Mac to restore it."
        )
        return summary

    # First, send any replies scheduled by a previous run that are now due.
    if not dry_run:
        _send_due_replies(summary)

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

        # If thread is waiting for a location, parse it out of the reply
        # (the message may contain more than just the venue).
        if thread_info.get("pending_meeting_at"):
            details = meeting_extractor.extract_meeting_details(msg["content"])
            location = ((details or {}).get("location") or "").strip()
            if location:
                _book_meeting_with_location(thread_id, location, thread_info, thread_info["pending_meeting_at"])
                summary["escalated"] += 1
                print(f"  ↳ Booked meeting for {thread_info['prospect_name']} at: {location}")
            else:
                _escalate(thread_id, inbound_id, "meeting_location_unclear", msg["content"])
                summary["escalated"] += 1
                print(
                    f"  ↳ Couldn't read a location from {thread_info['prospect_name']}'s "
                    "reply — escalated."
                )
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

        # Store draft with a humanlike scheduled delay — no blocking sleep,
        # so the next prospect's reply is drafted immediately.
        delay = random.randint(_DELAY_MIN_S, _DELAY_MAX_S)
        draft_id = _store_auto_draft(thread_id, reply_text, delay_s=delay)
        print(f"  ↳ Scheduled message {draft_id} to send in ~{delay // 60}m.")

    # Flush: wait (briefly, in small steps) for this run's scheduled replies
    # and send them as they come due. Anything still pending is picked up at
    # the start of the next cycle.
    if not dry_run:
        flush_start = time.monotonic()
        while True:
            remaining = _send_due_replies(summary)
            if remaining == 0:
                break
            if time.monotonic() - flush_start > _FLUSH_MAX_WAIT_S:
                print(f"  ↳ {remaining} scheduled repl(ies) left for the next cycle.")
                break
            time.sleep(20)

    return summary
