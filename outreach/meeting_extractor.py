"""Extract meeting details from a prospect's confirmed message using Claude API.

When a prospect says something like "sure, Tuesday 3pm works, Bangsar coffee?",
this module parses it into a structured dict with date, time, and location.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import anthropic

from outreach.config import ANTHROPIC_API_KEY

_MYT = timezone(timedelta(hours=8))


def extract_meeting_details(message: str, reference_date: datetime | None = None) -> dict | None:
    """Use Claude to extract meeting date, time, and location from a message.

    Returns a dict with keys: date (YYYY-MM-DD), time (HH:MM), location (str)
    or None if no clear meeting details are found.
    """
    if not ANTHROPIC_API_KEY:
        return None

    now = reference_date or datetime.now(_MYT)
    today_str = now.strftime("%A %d %B %Y")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=f"""\
Today is {today_str} (Malaysia time, MYT UTC+8).
Extract meeting details from the message below.
Return ONLY a JSON object with these keys:
  date: "YYYY-MM-DD" (resolve relative days like "Tuesday" or "next week" to actual dates)
  time: "HH:MM" (24-hour format)
  location: "place name or empty string if not mentioned"

If no clear meeting date/time is mentioned, return: {{"date": null, "time": null, "location": ""}}
Return raw JSON only. No explanation.\
""",
        messages=[{"role": "user", "content": message}],
    )

    try:
        raw = response.content[0].text.strip()
        data = json.loads(raw)
        if data.get("date") and data.get("time"):
            return data
        return None
    except Exception:  # noqa: BLE001
        return None


def build_meeting_datetime(details: dict) -> datetime | None:
    """Convert extracted details dict to a timezone-aware datetime."""
    try:
        date_str = details["date"]
        time_str = details["time"]
        dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=_MYT)
    except Exception:  # noqa: BLE001
        return None
