"""Generate and send the daily 5PM lead report to Telegram.

Report format:
  📊 Daily Lead Report — DD Mon YYYY
  🆕 New Leads (N)
  💬 Active Conversations (N)
  📅 Meetings Booked (N)
  Totals line
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from outreach.db.connection import get_connection
from outreach.telegram_client import send_operator_message

_MYT = timezone(timedelta(hours=8))


def _status_emoji(thread: dict) -> str:
    """Pick a status emoji based on last activity."""
    last_inbound = thread.get("last_inbound_at")
    last_outbound = thread.get("last_outbound_at")
    status = (thread.get("status") or "").lower()

    if "closed" in status or "ghosted" in status or "declined" in status:
        return "🔴"
    if last_inbound and last_outbound:
        # Prospect replied after our last message — warm
        if last_inbound > last_outbound:
            return "🟢"
    # Waiting on prospect
    return "🟡"


def _last_message_summary(thread_id: int, conn) -> str:
    """Return a short summary of the last message in this thread.

    Distinguishes by message status — never labels a draft/skipped message
    as 'Sent:' (that's misleading in the daily report).
    """
    row = conn.execute(
        """
        SELECT direction, content, status FROM messages
        WHERE thread_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (thread_id,),
    ).fetchone()
    if not row:
        return "No messages yet"

    status = row["status"]
    if row["direction"] == "inbound":
        prefix = "Replied:"
    elif status == "sent":
        prefix = "Sent:"
    elif status == "auto_draft":
        prefix = "Auto-drafted (sending soon):"
    elif status in ("draft", "edited"):
        prefix = "Draft pending:"
    elif status == "approved":
        prefix = "Approved (queued to send):"
    elif status == "skipped":
        prefix = "Skipped:"
    else:
        prefix = f"{status.capitalize()}:"
    preview = row["content"].replace("\n", " ")[:60]
    return f"{prefix} {preview}…"


def generate_report() -> str:
    """Build the daily report string."""
    now = datetime.now(_MYT)
    today = now.strftime("%Y-%m-%d")
    display_date = now.strftime("%-d %b %Y")

    conn = get_connection()
    try:
        # New leads — threads created today
        new_threads = conn.execute(
            """
            SELECT t.id, p.name, p.company, p.category
            FROM threads t
            JOIN prospects p ON t.prospect_id = p.id
            WHERE DATE(t.created_at, 'localtime') = ?
            ORDER BY t.created_at ASC
            """,
            (today,),
        ).fetchall()

        # Active conversations — only count threads where at least one
        # message has actually been sent (not just drafted/skipped).
        active_threads = conn.execute(
            """
            SELECT t.id, t.status, t.last_inbound_at, t.last_outbound_at,
                   t.outbound_count, t.inbound_count,
                   p.name, p.company
            FROM threads t
            JOIN prospects p ON t.prospect_id = p.id
            WHERE t.status = 'active'
              AND EXISTS (
                SELECT 1 FROM messages m
                WHERE m.thread_id = t.id AND m.status = 'sent'
              )
            ORDER BY t.updated_at DESC
            """,
        ).fetchall()

        # Drafts pending operator approval
        pending_drafts = conn.execute(
            """
            SELECT m.id, p.name, p.company, m.status
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.status IN ('draft', 'edited')
            ORDER BY m.created_at ASC
            """,
        ).fetchall()

        # Meetings booked today
        meetings = conn.execute(
            """
            SELECT target FROM audit_log
            WHERE action = 'meeting_booked'
              AND success = 1
              AND DATE(timestamp, 'localtime') = ?
            """,
            (today,),
        ).fetchall()

        # Get prospect names for booked meetings
        meeting_lines = []
        for m in meetings:
            target = m["target"] or ""
            if "prospect:" in target:
                prospect_id = target.split(":")[-1]
                p_row = conn.execute(
                    "SELECT name, company FROM prospects WHERE id = ?",
                    (prospect_id,),
                ).fetchone()
                if p_row:
                    # Try to get meeting time from calendar events created today
                    meeting_lines.append(f"- {p_row['name']} ({p_row['company']})")

    finally:
        conn.close()

    lines = [f"📊 *Daily Lead Report* — {display_date}", ""]

    # New leads
    lines.append(f"🆕 *New Leads* ({len(new_threads)})")
    if new_threads:
        for t in new_threads:
            category = (t["category"] or "").split(",")[0].strip()
            lines.append(f"- {t['name']} — {t['company'] or 'unknown'}, {category}")
    else:
        lines.append("- None today")
    lines.append("")

    # Active conversations (only threads with a sent message)
    lines.append(f"💬 *Active Conversations* ({len(active_threads)})")
    if active_threads:
        for t in active_threads:
            emoji = _status_emoji(dict(t))
            summary = _last_message_summary(t["id"], get_connection())
            lines.append(f"- {t['name']} — {summary} {emoji}")
    else:
        lines.append("- None active")
    lines.append("")

    # Drafts pending your approval
    lines.append(f"📝 *Drafts Pending Your Approval* ({len(pending_drafts)})")
    if pending_drafts:
        for d in pending_drafts:
            tag = " [edited]" if d["status"] == "edited" else ""
            lines.append(f"- {d['name']} ({d['company'] or 'unknown'}){tag}")
    else:
        lines.append("- None pending")
    lines.append("")

    # Meetings booked
    lines.append(f"📅 *Meetings Booked* ({len(meeting_lines)})")
    if meeting_lines:
        for ml in meeting_lines:
            lines.append(ml)
    else:
        lines.append("- None today")
    lines.append("")

    lines.append(
        f"—\nTotals: {len(new_threads)} new · "
        f"{len(active_threads)} active · "
        f"{len(pending_drafts)} pending · "
        f"{len(meeting_lines)} booked"
    )

    return "\n".join(lines)


def send_daily_report() -> None:
    """Generate and send the daily report to Telegram."""
    report = generate_report()
    send_operator_message(report, parse_mode="Markdown")
