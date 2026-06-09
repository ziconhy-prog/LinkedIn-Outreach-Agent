"""Poll the LinkedIn messaging inbox for new replies from known prospects.

Navigates to linkedin.com/messaging/ via Playwright and extracts recent
conversations. Matches senders against prospects we have active threads for
using profile URL or name.

Returns a list of NewMessage dicts ready to be stored and processed.
"""

from __future__ import annotations

from typing import TypedDict

from outreach.playwright_client import linkedin_session


class NewMessage(TypedDict):
    prospect_id: int
    thread_id: int
    linkedin_url: str
    sender_name: str
    content: str


# JS that extracts the most recent conversations from the messaging inbox.
# Returns up to `limit` conversations with sender URL, name, and last message text.
_EXTRACT_INBOX_JS = """
(limit) => {
    const results = [];

    // Conversation list items
    const convSelectors = [
        'li.msg-conversation-listitem',
        'li[data-control-name="overlay.open_thread"]',
        '.msg-conversations-container__convo-item',
        'ul.msg-conversations-container__conversations li',
    ];

    let items = [];
    for (const sel of convSelectors) {
        items = Array.from(document.querySelectorAll(sel));
        if (items.length > 0) break;
    }

    for (const item of items.slice(0, limit)) {
        // Profile link — extract /in/ slug
        const link = item.querySelector('a[href*="/in/"]');
        const profileUrl = link
            ? 'https://www.linkedin.com/in/' +
              (link.href.match(/\\/in\\/([^/?#]+)/) || [])[1]
            : null;

        // Sender name
        let name = '';
        for (const sel of [
            '.msg-conversation-listitem__participant-names',
            '.conversation-person-name',
            '.msg-thread__link-to-profile',
        ]) {
            const el = item.querySelector(sel);
            if (el) { name = el.innerText.trim(); break; }
        }
        if (!name && link) name = link.innerText.replace(/\\s+/g, ' ').trim();

        // Last message preview
        let preview = '';
        for (const sel of [
            '.msg-conversation-listitem__message-snippet',
            '.msg-conversation-card__message-snippet-body',
        ]) {
            const el = item.querySelector(sel);
            if (el) { preview = el.innerText.trim(); break; }
        }

        // Unread badge
        const hasUnread = !!item.querySelector(
            '.msg-conversation-listitem__unread-count, ' +
            '.notification-badge, ' +
            '[data-test-is-unread]'
        );

        if (profileUrl || name) {
            results.push({
                profile_url: profileUrl,
                name: name,
                preview: preview,
                has_unread: hasUnread,
            });
        }
    }
    return results;
}
"""

# JS to extract the full text of the latest inbound message inside an open thread.
_EXTRACT_THREAD_MESSAGES_JS = """
() => {
    const messages = [];
    const msgSelectors = [
        '.msg-s-message-list__event',
        '.msg-s-event-listitem',
    ];
    let items = [];
    for (const sel of msgSelectors) {
        items = Array.from(document.querySelectorAll(sel));
        if (items.length > 0) break;
    }
    for (const item of items) {
        // Skip messages sent by Zico (look for "You" indicator)
        const isSelf = !!item.querySelector(
            '.msg-s-message-group__meta time[aria-label*="You"], ' +
            '.msg-s-event__sender[aria-label*="You"]'
        );
        const bodyEl = item.querySelector('.msg-s-event-listitem__body, .msg-s-message__content');
        if (!bodyEl) continue;
        const text = bodyEl.innerText.trim();
        if (text && text.length > 2) {
            messages.push({ is_self: isSelf, text: text });
        }
    }
    return messages;
}
"""


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.split("?")[0].split("#")[0].rstrip("/")
    if not url.startswith("http"):
        return None
    return url.lower()


def poll_inbox(active_threads: list[dict]) -> list[NewMessage]:
    """Check LinkedIn inbox for new inbound messages from known prospects.

    Args:
        active_threads: List of dicts with keys: prospect_id, thread_id,
            linkedin_url, prospect_name, last_inbound_at.

    Returns:
        List of NewMessage dicts for each new inbound message found.
    """
    if not active_threads:
        return []

    # Build lookup maps for fast matching.
    by_url: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for t in active_threads:
        url = _normalize_url(t.get("linkedin_url"))
        if url:
            by_url[url] = t
        name = (t.get("prospect_name") or "").strip().lower()
        if name:
            by_name[name] = t

    results: list[NewMessage] = []

    with linkedin_session(headless=True) as page:
        page.goto("https://www.linkedin.com/messaging/", wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        page.wait_for_timeout(3_000)

        conversations = page.evaluate(_EXTRACT_INBOX_JS, 20)
        if not isinstance(conversations, list):
            return []

        for conv in conversations:
            # Match by URL first, then by name.
            conv_url = _normalize_url(conv.get("profile_url"))
            thread_info = by_url.get(conv_url) if conv_url else None

            if thread_info is None:
                conv_name = (conv.get("name") or "").strip().lower()
                thread_info = by_name.get(conv_name)

            if thread_info is None:
                continue  # Not a prospect we're tracking.

            # Only fetch full message if there's something to read.
            preview = (conv.get("preview") or "").strip()
            if not preview:
                continue

            # Navigate into the thread to get the full latest inbound message.
            try:
                if conv_url:
                    # LinkedIn messaging thread from profile URL:
                    thread_url = conv_url + "overlay/messaging-thread-from-member/"
                    page.goto(thread_url, wait_until="domcontentloaded")
                    try:
                        page.wait_for_load_state("networkidle", timeout=10_000)
                    except Exception:
                        pass
                    page.wait_for_timeout(2_000)

                messages = page.evaluate(_EXTRACT_THREAD_MESSAGES_JS)
                if not isinstance(messages, list) or not messages:
                    continue

                # Last inbound message in the thread.
                inbound = [m for m in messages if not m.get("is_self")]
                if not inbound:
                    continue

                last_inbound = inbound[-1]["text"]

                results.append(
                    NewMessage(
                        prospect_id=thread_info["prospect_id"],
                        thread_id=thread_info["thread_id"],
                        linkedin_url=thread_info["linkedin_url"],
                        sender_name=conv.get("name") or thread_info.get("prospect_name", ""),
                        content=last_inbound,
                    )
                )
            except Exception:  # noqa: BLE001
                continue

    return results
