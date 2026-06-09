"""Google Calendar integration for booking meetings with prospects.

One-time setup: run `python -m outreach connect-calendar` to authenticate.
This opens a browser, you log in to Google, and the OAuth token is saved
to data/google_oauth_token.json for all future runs.

After setup, the bot can:
- Check if Zico is free at a proposed time (free/busy query)
- Create a block-only calendar event when a meeting is confirmed
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from outreach.config import DATA_DIR, PROJECT_ROOT

_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
]

_MYT = timezone(timedelta(hours=8))  # Malaysia Time UTC+8


def _credentials_path() -> Path:
    import os
    raw = os.getenv("GOOGLE_OAUTH_CREDENTIALS_PATH", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return DATA_DIR / "google_credentials.json"


def _token_path() -> Path:
    import os
    raw = os.getenv("GOOGLE_OAUTH_TOKEN_PATH", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return DATA_DIR / "google_oauth_token.json"


def _get_service():
    """Return an authenticated Google Calendar service object."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token = _token_path()
    creds = None

    if token.exists():
        creds = Credentials.from_authorized_user_file(str(token), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token.write_text(creds.to_json())
        else:
            raise RuntimeError(
                "Google Calendar is not connected. "
                "Run `python -m outreach connect-calendar` first."
            )

    return build("calendar", "v3", credentials=creds)


def run_oauth_flow() -> None:
    """Run the one-time browser OAuth flow and save the token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = _credentials_path()
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google credentials file not found at {creds_path}. "
            "Download it from Google Cloud Console and set GOOGLE_OAUTH_CREDENTIALS_PATH in .env"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), _SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    token = _token_path()
    token.write_text(creds.to_json())
    print(f"✅ Google Calendar connected. Token saved to {token}")


def is_free(start: datetime, end: datetime) -> bool:
    """Return True if Zico's calendar shows no events in the given window."""
    service = _get_service()
    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": "primary"}],
    }
    result = service.freebusy().query(body=body).execute()
    busy = result.get("calendars", {}).get("primary", {}).get("busy", [])
    return len(busy) == 0


def create_meeting_event(
    prospect_name: str,
    company: str,
    linkedin_url: str,
    start: datetime,
    duration_minutes: int = 60,
    location: str = "",
) -> str:
    """Create a calendar event and return the event URL."""
    service = _get_service()

    end = start + timedelta(minutes=duration_minutes)
    title = f"LinkedIn meeting — {prospect_name} ({company})"

    description_parts = [
        f"Prospect: {prospect_name}",
        f"Company: {company}",
        f"LinkedIn: {linkedin_url}",
    ]
    if location:
        description_parts.append(f"Location: {location}")

    event = {
        "summary": title,
        "location": location,
        "description": "\n".join(description_parts),
        "start": {
            "dateTime": start.isoformat(),
            "timeZone": "Asia/Kuala_Lumpur",
        },
        "end": {
            "dateTime": end.isoformat(),
            "timeZone": "Asia/Kuala_Lumpur",
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60},
                {"method": "popup", "minutes": 15},
            ],
        },
    }

    created = service.events().insert(calendarId="primary", body=event).execute()
    return created.get("htmlLink", "")


# ---------------------------------------------------------------------------
# Natural language date/time parser
# ---------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def parse_meeting_text(text: str) -> Optional[dict]:
    """Parse natural language meeting text into structured data.

    Handles inputs like:
      "booked Xia Dan 20 May 2pm Bangsar"
      "booked Bernard 15 June 10:30am KL Sentral"
      "booked Xia Dan 20 May 2pm"

    Returns dict with keys: name, day, month, hour, minute, location
    or None if parsing fails.
    """
    lower = text.lower()

    # Extract time — e.g. "2pm", "10:30am", "14:00"
    time_match = re.search(
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', lower
    )
    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    meridiem = time_match.group(3)

    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0

    # Extract month and day
    month = None
    day = None
    for month_name, month_num in _MONTHS.items():
        if month_name in lower:
            month = month_num
            # Find day number near the month name
            idx = lower.index(month_name)
            surrounding = lower[max(0, idx - 5): idx + len(month_name) + 5]
            day_match = re.search(r'\d{1,2}', surrounding)
            if day_match:
                day = int(day_match.group())
            break

    if not month or not day:
        return None

    # Extract name (word after "booked")
    name_match = re.search(r'booked\s+([a-z\s]+?)(?:\d)', lower)
    name = name_match.group(1).strip().title() if name_match else ""

    # Extract location (everything after the time)
    time_end = time_match.end()
    location = text[time_end:].strip().strip(",").strip()

    now = datetime.now(_MYT)
    year = now.year if month >= now.month else now.year + 1

    return {
        "name": name,
        "day": day,
        "month": month,
        "year": year,
        "hour": hour,
        "minute": minute,
        "location": location,
    }


def parse_and_book(
    text: str,
    prospect_name: str,
    company: str,
    linkedin_url: str,
) -> tuple[bool, str]:
    """Parse meeting text, check free/busy, create event.

    Returns (success, message).
    """
    parsed = parse_meeting_text(text)
    if not parsed:
        return False, "Couldn't parse the date and time. Try: 'booked Xia Dan 20 May 2pm Bangsar'"

    try:
        start = datetime(
            parsed["year"], parsed["month"], parsed["day"],
            parsed["hour"], parsed["minute"],
            tzinfo=_MYT,
        )
    except ValueError as e:
        return False, f"Invalid date: {e}"

    end = start + timedelta(hours=1)

    try:
        free = is_free(start, end)
    except RuntimeError as e:
        return False, str(e)

    if not free:
        return False, (
            f"You have a conflict at {start.strftime('%d %b %Y %I:%M%p')} MYT. "
            "Check your calendar and pick another time."
        )

    try:
        event_url = create_meeting_event(
            prospect_name=prospect_name,
            company=company,
            linkedin_url=linkedin_url,
            start=start,
            location=parsed.get("location", ""),
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Failed to create calendar event: {exc}"

    return True, (
        f"✅ Meeting booked!\n"
        f"{prospect_name} ({company})\n"
        f"{start.strftime('%A, %d %B %Y at %I:%M%p')} MYT\n"
        f"Location: {parsed.get('location') or 'TBC'}\n"
        f"Calendar: {event_url}"
    )
