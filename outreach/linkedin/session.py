"""LinkedIn session: one-time login + status check.

Login uses the operator's real account in a visible browser window. Their
password and 2FA never go through this code — they type into the browser
directly. The resulting session is persisted in PLAYWRIGHT_USER_DATA_DIR.
"""

from __future__ import annotations

from outreach import audit
from outreach.config import PLAYWRIGHT_USER_DATA_DIR
from outreach.playwright_client import linkedin_session


def perform_login() -> bool:
    """Open a visible browser at LinkedIn login. Operator logs in manually.

    Returns True if a logged-in feed page is detected, False otherwise.
    """
    print("🌐 Opening browser to LinkedIn login...")
    print("   Log in normally (email, password, 2FA if prompted).")
    print("   Once you reach your home feed, return HERE and press Enter.")
    print()

    with linkedin_session(headless=False) as page:
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        try:
            input("   ⏸  Press Enter once you're logged in and on the feed... ")
        except (EOFError, KeyboardInterrupt):
            print("\n   Cancelled.")
            audit.log("linkedin_login", success=False, error_message="cancelled")
            return False

        # Verify we landed somewhere logged-in (feed, in/, mynetwork, etc.)
        current = page.url
        is_logged_in = (
            "linkedin.com" in current
            and "/login" not in current
            and "/checkpoint" not in current
        )

    if is_logged_in:
        print(f"✅ Logged in. Session saved to {PLAYWRIGHT_USER_DATA_DIR}")
        audit.log("linkedin_login", target=current, success=True)
        return True

    print("⚠️  Couldn't verify login. URL was:", current)
    print("   You may still be on the login screen. Run linkedin-login again.")
    audit.log("linkedin_login", target=current, success=False,
              error_message=f"final url not logged-in: {current}")
    return False


def check_session() -> bool:
    """Headless check: does the session land on a logged-in feed page?

    Returns True if logged in. Never raises — failure paths return False
    so callers can decide whether to prompt for re-login.
    """
    try:
        with linkedin_session(headless=True) as page:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            current = page.url
            ok = "/feed" in current and "/login" not in current
            audit.log(
                "linkedin_session_check",
                target=current,
                success=ok,
                error_message=None if ok else f"redirected to {current}",
            )
            return ok
    except Exception as exc:  # noqa: BLE001
        audit.log(
            "linkedin_session_check",
            success=False,
            error_message=f"{type(exc).__name__}: {exc}",
        )
        return False
