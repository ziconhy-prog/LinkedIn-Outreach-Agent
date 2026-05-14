"""Read a LinkedIn profile: headline + last N posts.

Consumes the profile-view rate budget — 1 unit for the profile page, 1 for
the activity page.

Implementation note: LinkedIn's class names are hash-suffixed and change
without warning. We avoid CSS classes and instead extract from page
structure: ``page.title()`` for the name, structured body text parsing for
headline and location, and ``article`` elements on the activity feed.
"""

from __future__ import annotations

from typing import Optional, TypedDict

from outreach import audit, rate_limiter
from outreach.playwright_client import linkedin_session


class ActivityItem(TypedDict):
    type: str   # 'post' | 'comment' | 'repost' | 'engagement'
    text: str


class ProfileData(TypedDict, total=False):
    url: str
    name: Optional[str]
    headline: Optional[str]
    location: Optional[str]
    activity: list[ActivityItem]


def _name_from_title(title: str) -> Optional[str]:
    """Extract person's name from a LinkedIn page title.

    LinkedIn formats profile titles as 'Name | LinkedIn' (or
    '(N) Name | LinkedIn' when notifications are showing).
    """
    if not title:
        return None
    parts = title.split("|", 1)
    head = parts[0].strip()
    # Strip leading "(N)" notification badge if present.
    if head.startswith("(") and ")" in head:
        head = head.split(")", 1)[1].strip()
    return head or None


def _is_noise_line(ln: str) -> bool:
    """Return True if a line is UI noise rather than profile data.

    Filters: very short fragments, verified badges, raised-dot separators,
    and other strings that shouldn't be treated as headline/location.
    """
    if not ln or len(ln) < 5:
        return True
    if ln.startswith("•") or ln.startswith("·"):
        return True
    stripped = ln.lstrip("• ·").strip()
    if stripped in {"You", "Verified", "Verified • You", "Contact info"}:
        return True
    return False


def _extract_headline_location(
    body_text: str, name: Optional[str]
) -> tuple[Optional[str], Optional[str]]:
    """Parse 'main' body text to find headline + location.

    On the logged-in profile-card view (scoped to ``<main>``), the first
    three substantive lines are reliably name, headline, location. We
    skip noise (verified badges, separators) defensively.
    """
    if not name:
        return None, None

    lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
    # Skip leading noise to get to name-anchored block.
    try:
        start = next(i for i, ln in enumerate(lines) if ln == name)
    except StopIteration:
        return None, None

    headline: Optional[str] = None
    location: Optional[str] = None
    for ln in lines[start + 1 : start + 12]:
        if ln == name or _is_noise_line(ln):
            continue
        if not headline:
            headline = ln
            continue
        if "," in ln and len(ln) < 120 and not ln.endswith(":"):
            location = ln
            break

    return headline, location


def _detect_activity_type(text: str) -> str:
    """Infer activity type from the first ~150 chars of raw inner_text.

    LinkedIn activity cards prefix reposts/comments with actor-description
    text before the actual content. We check for those markers first.
    """
    prefix = text[:150].lower()
    if any(w in prefix for w in ("reposted", " shared ")):
        return "repost"
    if "commented" in prefix:
        return "comment"
    if any(w in prefix for w in ("likes ", "celebrated", "loves ", "supports ", "reacted")):
        return "engagement"
    return "post"


# Selectors for activity-feed post elements. We try in order; the first
# locator that returns matches wins. LinkedIn rotates between these.
_POST_SELECTORS: tuple[str, ...] = (
    "div[data-urn*='activity']",
    "div[data-urn*='ugcPost']",
    "article",
)


def read_profile(url: str, max_posts: int = 5) -> ProfileData:
    """Read headline + last N posts from a LinkedIn profile URL.

    Two profile-view-budget units are consumed (profile page + activity page).
    Raises RateLimitExceeded if either exceeds today's budget.
    """
    rate_limiter.check("profile_view")
    rate_limiter.check("profile_view")  # second view comes a moment later

    out: ProfileData = {"url": url, "activity": []}
    activity_url = url.rstrip("/") + "/recent-activity/all/"

    try:
        with linkedin_session(headless=True) as page:
            # ---- Profile page: name, headline, location ----
            page.goto(url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass  # some profile pages never settle; continue anyway
            page.wait_for_timeout(1_500)

            out["name"] = _name_from_title(page.title())
            try:
                main_text = page.locator("main").inner_text(timeout=10_000)
            except Exception:
                main_text = ""
            headline, location = _extract_headline_location(main_text, out["name"])
            out["headline"] = headline
            out["location"] = location

            audit.log("profile_view", target=url, success=True)

            # ---- Activity page: last N posts ----
            page.goto(activity_url, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            page.wait_for_timeout(3_000)

            activity: list[ActivityItem] = []
            for selector in _POST_SELECTORS:
                elems = page.locator(selector).all()
                if not elems:
                    continue
                for el in elems:
                    if len(activity) >= max_posts:
                        break
                    try:
                        text = el.inner_text(timeout=2_000).strip()
                    except Exception:
                        continue
                    if len(text) < 60:
                        continue
                    activity.append({
                        "type": _detect_activity_type(text),
                        "text": text[:1_500],
                    })
                if activity:
                    break
            out["activity"] = activity

            audit.log("profile_view", target=activity_url, success=True)

        return out
    except Exception as exc:  # noqa: BLE001
        audit.log(
            "profile_view",
            target=url,
            success=False,
            error_message=f"{type(exc).__name__}: {exc}",
        )
        raise
