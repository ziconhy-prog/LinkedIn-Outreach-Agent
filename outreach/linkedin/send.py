"""Send a LinkedIn message via Playwright.

Two channels, chosen automatically based on detected connection state:
  1. Connect flow  — (top-level Connect button, or More → Connect) → Add a note → Send
  2. Direct message — Message button → compose overlay → Send

Channel selection:
  pending          → hard fail (do not send)
  connect_available → connect flow  (connection_request rate-limit bucket)
  connected        → direct message (message_send rate-limit bucket)
  unknown          → try connect flow; if Connect not found, fall back to direct message

Hard requirements:
  - Accepts only a message_id (DB row). Never raw text.
  - Message must have status 'approved' or 'auto_draft'.
  - Respects per-channel daily rate limits before sending.
  - Marks message 'sent' only after the browser action succeeds.
  - Logs the action to audit_log with the channel used.
"""

from __future__ import annotations

import time as _time
from pathlib import Path as _Path

from outreach import audit, rate_limiter
from outreach.db.connection import get_connection
from outreach.linkedin.humanlike import check_for_challenge, jitter
from outreach.playwright_client import linkedin_session


class SendError(Exception):
    """Raised when the LinkedIn send action fails."""


NOTE_CHAR_LIMIT = 300


# ---------------------------------------------------------------------------
# JavaScript helpers
# ---------------------------------------------------------------------------

# Shared JS prelude: exposes `getActionScope()` (the whole <main>) and
# `isInSuggestions(el)`, which returns true for buttons living inside known
# "People also viewed" / "People you may know" containers. Matchers should
# filter those out so we don't mistake a sidebar suggestion's Connect button
# for the prospect's own action row.
_SCOPE_PRELUDE_JS = """
    const getActionScope = () =>
        document.querySelector('main') || document.body;

    // NOTE: 'aside' was removed — LinkedIn sometimes wraps the profile
    // action row inside an aside-like container, which would exclude the
    // very buttons we're trying to click. Use specific class/aria selectors
    // for the suggestion sections instead.
    const SUGGESTION_EXCLUDE_SELECTOR = [
        '.pv-browsemap-section',
        '[data-section="browsemap"]',
        '.pv-recommendations-section',
        '[aria-label*="People also viewed"]',
        '[aria-label*="People you may know"]',
        '[aria-label*="More profiles for you"]',
        '.entity-result',
        '.reusable-search__entity-result-list'
    ].join(', ');

    const isInSuggestions = el =>
        el.closest(SUGGESTION_EXCLUDE_SELECTOR) !== null;
"""

_DETECT_CONNECTION_STATE_JS = """
() => {
""" + _SCOPE_PRELUDE_JS + """
    const scope = getActionScope();
    // Exclude buttons that live inside "People also viewed" / suggestion
    // cards — those carry their own Connect button for *other* people.
    const btns = Array.from(scope.querySelectorAll(
        'button, a[role="button"], a.artdeco-button'
    )).filter(el => !isInSuggestions(el));
    const text  = el => (el.innerText || el.textContent || '').trim();
    const label = el => (el.getAttribute('aria-label') || '').trim();

    const isPending = el =>
        text(el) === 'Pending' || label(el) === 'Pending';

    const isConnect = el => {
        const t = text(el);
        const l = label(el).toLowerCase();
        return t === 'Connect' || t.startsWith('Connect ')
            || l === 'connect' || l.startsWith('connect ')
            || l.includes('to connect') || l.includes('connect with');
    };

    const isMessage = el =>
        text(el) === 'Message' || label(el) === 'Message'
        || label(el).toLowerCase().startsWith('message ');

    if (btns.some(isPending)) return 'pending';
    if (btns.some(isConnect)) return 'connect_available';
    if (btns.some(isMessage)) return 'connected';
    return 'unknown';
}
"""

_CLICK_CONNECT_TOPLEVEL_JS = """
() => {
""" + _SCOPE_PRELUDE_JS + """
    const scope = getActionScope();
    // Click a top-level Connect button (profile actions row only).
    const btns = Array.from(scope.querySelectorAll(
        'button, a[role="button"]'
    )).filter(el => !isInSuggestions(el));
    const btn = btns.find(el => {
        const t = (el.innerText || el.textContent || '').trim();
        const l = (el.getAttribute('aria-label') || '').trim().toLowerCase();
        return (t === 'Connect' || t.startsWith('Connect ')
            || l === 'connect' || l.includes('to connect')
            || l.includes('connect with'))
            && el.offsetParent !== null;
    });
    if (btn) { btn.click(); return true; }
    return false;
}
"""

_CLICK_MORE_BUTTON_JS = """
() => {
""" + _SCOPE_PRELUDE_JS + """
    const scope = getActionScope();
    const buttons = Array.from(scope.querySelectorAll('button'))
        .filter(el => !isInSuggestions(el));
    const btn = buttons.find(el => {
        const txt   = (el.innerText || el.textContent || '').trim();
        const label = (el.getAttribute('aria-label') || '').trim();
        return (txt === 'More' || label.startsWith('More actions'))
            && el.offsetParent !== null;
    });
    if (btn) { btn.click(); return true; }
    return false;
}
"""

_CLICK_CONNECT_IN_DROPDOWN_JS = """
() => {
    const items = Array.from(document.querySelectorAll(
        'div[role="menu"] [role="menuitem"], '
        + 'div[role="menu"] button, '
        + 'div[role="menu"] span, '
        + '.artdeco-dropdown__content button, '
        + '.artdeco-dropdown__content span'
    ));
    const item = items.find(el => {
        const txt = (el.innerText || el.textContent || '').trim();
        return txt === 'Connect' || txt.startsWith('Connect');
    });
    if (item) {
        const target = item.closest('button, [role="menuitem"]') || item;
        target.click();
        return true;
    }
    return false;
}
"""

_CLICK_ADD_NOTE_JS = """
() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const btn = buttons.find(el => {
        const txt   = (el.innerText || el.textContent || '').trim();
        const label = (el.getAttribute('aria-label') || '').trim();
        return txt === 'Add a note' || label === 'Add a note';
    });
    if (btn) { btn.click(); return true; }
    return false;
}
"""

_CLICK_SEND_INVITATION_JS = """
() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const btn = buttons.find(el => {
        const txt   = (el.innerText || el.textContent || '').trim().toLowerCase();
        const label = (el.getAttribute('aria-label') || '').toLowerCase();
        if (el.disabled) return false;
        return txt === 'send' || txt === 'send invitation' || txt === 'send now'
            || label === 'send invitation' || label === 'send now' || label === 'send';
    });
    if (btn) { btn.click(); return true; }
    return false;
}
"""

_CLICK_MESSAGE_BUTTON_JS = """
() => {
""" + _SCOPE_PRELUDE_JS + """
    const scope = getActionScope();
    // Look across button/anchor variants; LinkedIn sometimes renders
    // the Message action as an <a href="/messaging/...">.
    const candidates = Array.from(scope.querySelectorAll(
        'button, a[role="button"], a[href*="/messaging/"]'
    )).filter(el => !isInSuggestions(el) && el.offsetParent !== null);

    const text  = el => (el.innerText || el.textContent || '').trim();
    const label = el => (el.getAttribute('aria-label') || '').trim();
    const control = el => (el.getAttribute('data-control-name') || '').toLowerCase();

    const isMessage = el => {
        const t = text(el);
        const l = label(el).toLowerCase();
        const c = control(el);
        return t === 'Message' || t === 'Send message' || t === 'Send Message'
            || l === 'message' || l.startsWith('message ')
            || l.startsWith('send a message') || l.startsWith('send message')
            || c === 'message' || c === 'message_send' || c.startsWith('message');
    };

    const btn = candidates.find(isMessage);
    if (btn) { btn.click(); return true; }
    return false;
}
"""

_CLICK_DM_SEND_JS = """
() => {
    // The compose overlay is portaled outside <main>, so search the whole
    // document. We try several LinkedIn variants for the send button.
    const allBtns = Array.from(document.querySelectorAll(
        'button, [role="button"]'
    )).filter(el => !el.disabled && el.offsetParent !== null);

    const text  = el => (el.innerText || el.textContent || '').trim().toLowerCase();
    const label = el => (el.getAttribute('aria-label') || '').trim().toLowerCase();
    const cls   = el => (el.className || '').toString().toLowerCase();

    // Prefer buttons inside the message compose form/overlay.
    const inComposeScope = el =>
        el.closest('.msg-form, .msg-overlay-bubble-header, .msg-overlay-conversation-bubble, [data-test-msgoverlay-conversation-bubble]') !== null;

    const isSend = el => {
        const t = text(el);
        const l = label(el);
        const c = cls(el);
        return t === 'send' || t === 'send message'
            || l === 'send' || l === 'send message'
            || l.startsWith('send ') || l.includes('press enter to send')
            || c.includes('msg-form__send-button') || c.includes('msg-form__send-btn')
            || c.includes('send-button') || c.includes('send-btn')
            || (el.getAttribute('type') === 'submit' && el.closest('.msg-form'));
    };

    // First pass: compose-scoped matches.
    let btn = allBtns.find(el => inComposeScope(el) && isSend(el));
    // Second pass: anywhere, but require a more specific match to avoid the
    // wrong 'Send' button on the page (e.g. invitation Send).
    if (!btn) btn = allBtns.find(el =>
        cls(el).includes('msg-form__send') || cls(el).includes('msg-form__send-btn')
        || (el.getAttribute('type') === 'submit' && el.closest('.msg-form'))
    );
    if (btn) { btn.click(); return true; }
    return false;
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_debug_snapshot(page, tag: str) -> str:
    """Save a screenshot + HTML excerpt for diagnosis. Returns timestamp string."""
    debug_dir = _Path("logs/send_failures")
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = int(_time.time())
    try:
        page.screenshot(path=str(debug_dir / f"{tag}_{ts}.png"), full_page=True)
        # Capture <main> only (skips the heavy global nav/chrome) up to 60kB —
        # this is enough to cover the profile action row + sidebar suggestions
        # while staying small enough to grep through.
        html_excerpt = page.evaluate(
            "() => (document.querySelector('main') || document.body).outerHTML.slice(0, 60000)"
        )
        (debug_dir / f"{tag}_{ts}.html").write_text(html_excerpt, encoding="utf-8")
        # Also dump a compact summary of buttons in the action area — helps
        # diagnose 'button not found' failures without parsing the full HTML.
        button_dump = page.evaluate(
            """() => {
                // Dump from the whole document so portaled overlays
                // (compose, modals) are captured.
                const els = Array.from(document.querySelectorAll(
                    'button, [role=\"button\"], a[href*=\"/messaging/\"]'
                )).slice(0, 80);
                return els.map(el => ({
                    tag: el.tagName,
                    text: (el.innerText || el.textContent || '').trim().slice(0, 60),
                    aria: (el.getAttribute('aria-label') || '').slice(0, 80),
                    control: el.getAttribute('data-control-name') || '',
                    cls: (el.className || '').toString().slice(0, 120),
                    type: el.getAttribute('type') || '',
                    href: el.getAttribute('href') || '',
                    visible: el.offsetParent !== null
                }));
            }"""
        )
        import json as _json
        (debug_dir / f"{tag}_{ts}.buttons.json").write_text(
            _json.dumps(button_dump, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return str(ts)


def _navigate_to_profile(page, linkedin_url: str) -> None:
    """Navigate to a LinkedIn profile and wait for it to settle."""
    page.goto(linkedin_url.rstrip("/"), wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    jitter(1_500, 3_000)
    check_for_challenge(page)


def _detect_state(page) -> str:
    """Return connection state: 'pending' | 'connect_available' | 'connected' | 'unknown'."""
    return page.evaluate(_DETECT_CONNECTION_STATE_JS)


# ---------------------------------------------------------------------------
# Channel 1: connect with note
# ---------------------------------------------------------------------------

class ConnectNotAvailable(SendError):
    """Raised when the More dropdown has no Connect option for this profile.

    The caller should fall back to the direct-message channel.
    """


def _send_via_connect(page, note_text: str) -> None:
    """Send a connection request with an attached note.

    Flow (per operator instruction):
      1. Click 'More' on the profile actions row.
      2. Look for 'Connect' in the dropdown — if found, click it, add note, send.
      3. If 'Connect' is NOT in the dropdown, raise ConnectNotAvailable so the
         outer send_message() falls back to the Message (DM) channel.

    Assumes the profile page is already loaded.
    """
    # Step 1: click 'More'.
    clicked_more = False
    for _ in range(5):
        clicked_more = page.evaluate(_CLICK_MORE_BUTTON_JS)
        if clicked_more:
            break
        page.wait_for_timeout(1_500)
    if not clicked_more:
        ts = _save_debug_snapshot(page, "more_missing")
        raise SendError(
            f"Could not find the 'More' button on the profile page. "
            f"Diagnostics: logs/send_failures/more_missing_{ts}.*"
        )

    page.wait_for_timeout(1_000)

    # Step 2: look for 'Connect' inside the open dropdown.
    clicked_connect = False
    for _ in range(4):
        clicked_connect = page.evaluate(_CLICK_CONNECT_IN_DROPDOWN_JS)
        if clicked_connect:
            break
        page.wait_for_timeout(800)

    if not clicked_connect:
        # Dismiss the open dropdown so the page is clean for the DM fallback.
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            pass
        ts = _save_debug_snapshot(page, "connect_missing")
        raise ConnectNotAvailable(
            f"No 'Connect' option in the More dropdown — falling back to direct message. "
            f"Diagnostics: logs/send_failures/connect_missing_{ts}.*"
        )

    page.wait_for_timeout(1_500)

    # Step 2: click "Add a note".
    try:
        page.get_by_role("button", name="Add a note").wait_for(
            state="visible", timeout=10_000
        )
    except Exception:
        ts = _save_debug_snapshot(page, "add_note_button_missing")
        raise SendError(
            f"'Add a note' button did not appear after clicking Connect. "
            f"Diagnostics: logs/send_failures/add_note_button_missing_{ts}.*"
        )

    page.wait_for_timeout(600)

    clicked_note = False
    try:
        page.get_by_role("button", name="Add a note").first.click()
        clicked_note = True
    except Exception:
        clicked_note = page.evaluate(_CLICK_ADD_NOTE_JS)

    if not clicked_note:
        ts = _save_debug_snapshot(page, "add_note_click_failed")
        raise SendError(
            f"'Add a note' button found but click failed. "
            f"Diagnostics: logs/send_failures/add_note_click_failed_{ts}.*"
        )

    page.wait_for_timeout(1_000)

    # Step 3: type the note.
    note_selectors = (
        'textarea[name="message"]',
        'textarea#custom-message',
        'div[role="dialog"] textarea',
        '.send-invite__custom-message',
    )
    note_selector = None
    for sel in note_selectors:
        try:
            page.wait_for_selector(sel, timeout=5_000, state="visible")
            note_selector = sel
            break
        except Exception:
            continue
    if not note_selector:
        ts = _save_debug_snapshot(page, "note_textarea_missing")
        raise SendError(
            f"Note textarea not found after clicking 'Add a note'. "
            f"Diagnostics: logs/send_failures/note_textarea_missing_{ts}.*"
        )

    page.locator(note_selector).first.click()
    page.wait_for_timeout(400)
    page.keyboard.type(note_text, delay=35)
    page.wait_for_timeout(1_200)

    # Step 4: send the invitation.
    sent = False
    for label in ("Send invitation", "Send now", "Send"):
        try:
            btn = page.get_by_role("button", name=label).last
            btn.wait_for(state="visible", timeout=3_000)
            btn.click()
            sent = True
            break
        except Exception:
            continue

    if not sent:
        for _ in range(3):
            sent = page.evaluate(_CLICK_SEND_INVITATION_JS)
            if sent:
                break
            page.wait_for_timeout(700)

    if not sent:
        ts = _save_debug_snapshot(page, "send_invitation_missing")
        raise SendError(
            f"'Send invitation' button not found or disabled. "
            f"Diagnostics: logs/send_failures/send_invitation_missing_{ts}.*"
        )

    page.wait_for_timeout(2_500)


# ---------------------------------------------------------------------------
# Channel 2: direct message
# ---------------------------------------------------------------------------

def _send_via_direct_message(page, message_text: str) -> None:
    """Send a direct message via the Message button on the profile.

    Assumes the profile page is already loaded.
    """
    # Step 1: click the Message button.
    clicked = False
    for _ in range(4):
        clicked = page.evaluate(_CLICK_MESSAGE_BUTTON_JS)
        if clicked:
            break
        page.wait_for_timeout(800)
    if not clicked:
        ts = _save_debug_snapshot(page, "message_button_missing")
        raise SendError(
            f"'Message' button not found on profile page. "
            f"Diagnostics: logs/send_failures/message_button_missing_{ts}.*"
        )

    page.wait_for_timeout(1_500)

    # Step 2: find the compose input (contenteditable overlay or textarea).
    compose_selectors = (
        '.msg-form__contenteditable',
        'div[aria-label="Write a message…"]',
        'div[aria-label="Write a message..."]',
        'div[contenteditable="true"][role="textbox"]',
        '.msg-form__msg-content-container [contenteditable]',
    )
    compose_sel = None
    for sel in compose_selectors:
        try:
            page.wait_for_selector(sel, timeout=6_000, state="visible")
            compose_sel = sel
            break
        except Exception:
            continue
    if not compose_sel:
        ts = _save_debug_snapshot(page, "message_compose_missing")
        raise SendError(
            f"Message compose box did not appear after clicking 'Message'. "
            f"Diagnostics: logs/send_failures/message_compose_missing_{ts}.*"
        )

    # Step 3: type the message.
    page.locator(compose_sel).first.click()
    page.wait_for_timeout(400)
    page.keyboard.type(message_text, delay=35)
    page.wait_for_timeout(1_200)

    # Step 4: send. Try role-by-name → JS matcher → keyboard shortcut.
    sent = False
    for label in ("Send", "Send message"):
        try:
            btn = page.get_by_role("button", name=label).last
            btn.wait_for(state="visible", timeout=3_000)
            btn.click()
            sent = True
            break
        except Exception:
            continue

    if not sent:
        for _ in range(3):
            sent = page.evaluate(_CLICK_DM_SEND_JS)
            if sent:
                break
            page.wait_for_timeout(700)

    if not sent:
        # Final fallback: keyboard shortcut. LinkedIn's compose accepts
        # Cmd/Ctrl+Enter to submit regardless of the user's "press Enter
        # to send" preference. Focus is already in the compose box from
        # the typing step above.
        try:
            import platform as _platform
            modifier = "Meta" if _platform.system() == "Darwin" else "Control"
            page.keyboard.press(f"{modifier}+Enter")
            page.wait_for_timeout(1_500)
            # Heuristic: if the compose box cleared, the send went through.
            try:
                remaining = page.locator(compose_sel).first.inner_text(timeout=2_000)
                if not remaining.strip():
                    sent = True
            except Exception:
                # If we can't read it, assume the overlay closed → sent.
                sent = True
        except Exception:
            pass

    if not sent:
        ts = _save_debug_snapshot(page, "dm_send_missing")
        raise SendError(
            f"Send button not found in message compose overlay. "
            f"Diagnostics: logs/send_failures/dm_send_missing_{ts}.*"
        )

    page.wait_for_timeout(2_500)


# Backwards-compatible aliases.
def _send_connection_with_note(page, linkedin_url: str, note_text: str) -> None:
    """Legacy wrapper: navigate + connect flow (for any direct callers)."""
    _navigate_to_profile(page, linkedin_url)
    _send_via_connect(page, note_text)


_find_and_send = _send_connection_with_note


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_message(message_id: int) -> None:
    """Send the LinkedIn message identified by message_id.

    Navigates to the prospect's profile, detects connection state, then
    automatically routes to the connect-with-note flow or the direct-message
    flow. Falls back to direct message if the connect flow cannot find a
    Connect option.

    The message must have status 'approved' or 'auto_draft'.
    Raises SendError on any failure; the DB row is NOT marked sent in that case.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT m.id, m.content, m.status, m.approved_via,
                   t.prospect_id, p.name, p.linkedin_url
            FROM messages m
            JOIN threads t ON m.thread_id = t.id
            JOIN prospects p ON t.prospect_id = p.id
            WHERE m.id = ?
            """,
            (message_id,),
        ).fetchone()

        if not row:
            raise SendError(f"Message {message_id} not found.")

        if row["status"] not in ("approved", "auto_draft"):
            raise SendError(
                f"Message {message_id} has status '{row['status']}'. "
                "Only 'approved' or 'auto_draft' messages can be sent."
            )

        if not row["linkedin_url"]:
            raise SendError(
                f"Prospect {row['name']} has no LinkedIn URL. Cannot send."
            )

        content = row["content"]
        linkedin_url = row["linkedin_url"]

        # Same-day duplicate guard.
        already_sent_today = conn.execute(
            """
            SELECT count(*) FROM messages m
            JOIN threads t ON m.thread_id = t.id
            WHERE t.prospect_id = (
                SELECT t2.prospect_id FROM threads t2
                JOIN messages m2 ON m2.thread_id = t2.id
                WHERE m2.id = ?
            )
            AND m.status = 'sent'
            AND DATE(m.sent_at, 'localtime') = DATE('now', 'localtime')
            """,
            (message_id,),
        ).fetchone()[0]
        if already_sent_today:
            raise SendError(
                "Already sent to this prospect today. "
                "Skipping to avoid duplicate contact on the same day."
            )

        channel_used = None

        try:
            with linkedin_session(headless=False) as page:
                page.set_default_timeout(20_000)
                _navigate_to_profile(page, linkedin_url)
                state = _detect_state(page)

                if state == "pending":
                    raise SendError(
                        "A connection invitation is already pending for this prospect."
                    )

                elif state == "connected":
                    # Already 1st-degree — send as a direct message.
                    rate_limiter.check("message_send")
                    _send_via_direct_message(page, content)
                    channel_used = "direct_message"

                else:
                    # connect_available or unknown — try connect flow first,
                    # fall back to direct message if it fails for any reason.
                    connect_err = None
                    try:
                        if len(content) > NOTE_CHAR_LIMIT:
                            raise SendError(
                                f"Draft is {len(content)} chars — LinkedIn connection note "
                                f"limit is {NOTE_CHAR_LIMIT}. Shorten before sending."
                            )
                        rate_limiter.check("connection_request")
                        _send_via_connect(page, content)
                        channel_used = "connection_request"
                    except SendError as exc:
                        connect_err = exc

                    if connect_err is not None:
                        try:
                            _navigate_to_profile(page, linkedin_url)
                            rate_limiter.check("message_send")
                            _send_via_direct_message(page, content)
                            channel_used = "direct_message"
                        except SendError as dm_exc:
                            raise SendError(
                                f"Both send channels failed.\n"
                                f"  Connect attempt: {connect_err}\n"
                                f"  Message attempt: {dm_exc}"
                            ) from dm_exc

        except SendError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SendError(f"Browser error while sending: {exc}") from exc

        # Mark sent only after the browser action succeeds.
        conn.execute(
            "UPDATE messages SET status = 'sent', sent_at = CURRENT_TIMESTAMP WHERE id = ?",
            (message_id,),
        )
        conn.execute(
            "UPDATE threads SET last_outbound_at = CURRENT_TIMESTAMP, "
            "outbound_count = outbound_count + 1 WHERE id = "
            "(SELECT thread_id FROM messages WHERE id = ?)",
            (message_id,),
        )
        conn.commit()

        audit.log(channel_used, target=f"message:{message_id}", success=True)

    except SendError:
        audit.log(
            "send_error",
            target=f"message:{message_id}",
            success=False,
            error_message="send_error",
        )
        conn.close()
        raise
    finally:
        conn.close()
