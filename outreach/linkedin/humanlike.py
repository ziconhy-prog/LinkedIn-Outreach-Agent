"""Humanlike browser behaviour for LinkedIn Playwright sessions.

Adds natural scrolling, mouse movement, and random timing jitter so the
session looks less like automated scraping and more like a person browsing.
"""

from __future__ import annotations

import random
import time
from typing import Any


# ---------------------------------------------------------------------------
# Jitter — random pauses between actions
# ---------------------------------------------------------------------------

def jitter(min_ms: int = 400, max_ms: int = 1_200) -> None:
    """Sleep for a random duration to simulate human reaction time."""
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def long_pause(min_s: float = 1.5, max_s: float = 4.0) -> None:
    """Longer pause — simulates reading or thinking."""
    time.sleep(random.uniform(min_s, max_s))


# ---------------------------------------------------------------------------
# Mouse movement
# ---------------------------------------------------------------------------

def random_mouse_move(page: Any) -> None:
    """Move the mouse to a random position on the visible page."""
    try:
        viewport = page.viewport_size or {"width": 1280, "height": 900}
        x = random.randint(100, int(viewport["width"] * 0.8))
        y = random.randint(100, int(viewport["height"] * 0.8))
        page.mouse.move(x, y)
        jitter(100, 400)
    except Exception:  # noqa: BLE001
        pass


def move_to_element_naturally(page: Any, selector: str) -> None:
    """Move mouse toward an element before interacting with it."""
    try:
        el = page.locator(selector).first
        box = el.bounding_box()
        if not box:
            return
        # Move to a slightly random point within the element.
        x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
        y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)
        page.mouse.move(x, y)
        jitter(150, 500)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Scrolling
# ---------------------------------------------------------------------------

def scroll_naturally(page: Any, direction: str = "down", passes: int = 3) -> None:
    """Scroll the page in a human pattern: variable speed, occasional pauses.

    Args:
        direction: 'down' or 'up'
        passes: how many scroll movements to make
    """
    sign = 1 if direction == "down" else -1
    for _ in range(passes):
        distance = random.randint(200, 600) * sign
        page.evaluate(
            f"""window.scrollBy({{
                top: {distance},
                behavior: 'smooth'
            }})"""
        )
        jitter(500, 1_500)
        # Occasional longer pause — simulates reading
        if random.random() < 0.3:
            long_pause(1.0, 2.5)


def scroll_to_bottom_gradually(page: Any) -> None:
    """Scroll from top to bottom of a page in several natural passes."""
    # First glance — quick scroll down
    scroll_naturally(page, "down", passes=2)
    random_mouse_move(page)
    long_pause(1.0, 2.0)

    # Slower read-through
    scroll_naturally(page, "down", passes=3)
    random_mouse_move(page)
    long_pause(0.8, 1.8)

    # Brief scroll back up — humans often re-read
    if random.random() < 0.4:
        scroll_naturally(page, "up", passes=1)
        long_pause(0.5, 1.2)
        scroll_naturally(page, "down", passes=2)


def scroll_feed_naturally(page: Any, post_count: int = 5) -> None:
    """Scroll through a LinkedIn activity feed naturally.

    Simulates reading posts: scroll down, pause on content, move mouse.
    """
    for i in range(post_count):
        scroll_naturally(page, "down", passes=random.randint(1, 2))
        random_mouse_move(page)
        # Longer pause on some posts — simulates actually reading
        if random.random() < 0.5:
            long_pause(1.5, 4.0)
        else:
            jitter(600, 1_400)


# ---------------------------------------------------------------------------
# Captcha / warning detection
# ---------------------------------------------------------------------------

_CHALLENGE_URL_FRAGMENTS = (
    "/checkpoint/",
    "/captcha/",
    "/challenge/",
    "/authwall",
    "/uas/login",
)

_CHALLENGE_BODY_PHRASES = (
    "unusual activity",
    "verify you're a human",
    "security check",
    "captcha",
    "let's do a quick security check",
    "we noticed some unusual",
    "confirm your identity",
    "restricted",
    "your account has been",
)


class LinkedInChallengeDetected(Exception):
    """Raised when LinkedIn shows a captcha or security challenge."""


def check_for_challenge(page: Any) -> None:
    """Raise LinkedInChallengeDetected if LinkedIn is showing a security wall.

    Call after any page navigation before extracting data.
    """
    url = page.url.lower()
    if any(frag in url for frag in _CHALLENGE_URL_FRAGMENTS):
        raise LinkedInChallengeDetected(
            f"LinkedIn challenge page detected: {page.url}"
        )

    try:
        body = page.locator("body").inner_text(timeout=3_000).lower()
        if any(phrase in body for phrase in _CHALLENGE_BODY_PHRASES):
            raise LinkedInChallengeDetected(
                "LinkedIn showing security/captcha prompt. "
                "Stop automation and log in manually to clear it."
            )
    except LinkedInChallengeDetected:
        raise
    except Exception:  # noqa: BLE001
        pass  # Body read failed — don't block on it.
