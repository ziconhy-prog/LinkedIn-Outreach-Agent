"""Browser session manager for Python-owned Playwright.

This is separate from the Playwright MCP we set up earlier. The MCP session
is for ad-hoc Claude Code exploration; this Python session is what the
production system uses long-term. Both can coexist on the same Mac as long
as only one has the browser open at a time.

The user-data directory persists the LinkedIn login across runs.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Page, sync_playwright

from outreach.config import PLAYWRIGHT_USER_DATA_DIR


# Pretend to be a normal Chromium user, not a stripped-down headless agent.
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


@contextmanager
def linkedin_session(headless: bool = True) -> Iterator[Page]:
    """Yield a Playwright Page using the persisted LinkedIn session.

    Set ``headless=False`` for interactive flows like first-time login.
    For autonomous searches and reads, headless is fine.
    """
    PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=_USER_AGENT,
            locale="en-US",
            timezone_id="Asia/Kuala_Lumpur",
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(15_000)
            yield page
        finally:
            context.close()
