"""Search LinkedIn for a profile URL by prospect name.

Workflow:
  1. Search by name only (no company in query — per CLAUDE.md rules).
  2. Extract top results with name, headline, and location from the result list.
  3. Validate each result: name match + SEA/Malaysia location + not AI competitor.
  4. Score by company/headline match if expected_company is provided.
  5. Return the best confident match, or None if no result is confident enough.

Rate budget: 2 profile-view units per search (results page + potential click).
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Optional

from outreach import audit, rate_limiter
from outreach.playwright_client import linkedin_session


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PROFILE_URL_RE = re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/in/[^/?#\s]+")

_SEA_TERMS = frozenset([
    "malaysia", "kuala lumpur", "kuala", " kl ", "selangor", "penang",
    "johor", "melaka", "perak", "sabah", "sarawak", "putrajaya",
    "petaling", "puchong", "subang", "cheras", "ampang", "klang",
    "singapore", "indonesia", "jakarta", "thailand", "bangkok",
    "philippines", "manila", "vietnam", "ho chi minh", "hanoi",
    "myanmar", "brunei", "cambodia",
])

# Profiles where these appear in the headline are deprioritised per CLAUDE.md.
_AI_COMPETITOR_TERMS = frozenset([
    "artificial intelligence company", "ai automation", "chatbot vendor",
    "agentic", "generative ai", "ai agent", "llm", "ai training provider",
    "ai solutions", "ai startup",
])

# Minimum score for a result to be returned as a confident match.
# Score breakdown: SEA location (+30), company/headline match (+20),
# name exact match bonus (+10).
_MIN_CONFIDENCE_SCORE = 30


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def _normalize_profile_url(href: str) -> Optional[str]:
    """Return a canonical https://www.linkedin.com/in/<slug> URL, or None."""
    if not href:
        return None
    if href.startswith("/in/"):
        href = f"https://www.linkedin.com{href}"
    match = _PROFILE_URL_RE.search(href)
    if not match:
        return None
    url = match.group(0)
    url = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return url


# ---------------------------------------------------------------------------
# Result extraction (Playwright page → structured list)
# ---------------------------------------------------------------------------

_EXTRACT_JS = """
(limit) => {
    const results = [];

    // Try known LinkedIn result-card selectors (most-to-least specific).
    const cardSelectors = [
        'li.reusable-search__result-container',
        'ul.reusable-search__entity-result-list > li',
        'li.search-result',
        '.search-results-container li',
    ];
    let cards = [];
    for (const sel of cardSelectors) {
        cards = Array.from(document.querySelectorAll(sel));
        if (cards.length > 0) break;
    }

    // Fallback: extract from bare /in/ links when card containers aren't found.
    // LinkedIn's link innerText bundles the full card: "Name • 1st Headline Location Message ..."
    // We parse out the name and use the cleaned blob as the location field so
    // SEA-term detection still works even without separate location elements.
    if (cards.length === 0) {
        const seen = new Set();
        const links = Array.from(document.querySelectorAll('a[href*="/in/"]'))
            .filter(a => {
                const m = a.href.match(/\\/in\\/([^/?#]+)/);
                return m && !seen.has(m[1]) && seen.add(m[1]);
            })
            .slice(0, limit);
        return links.map(link => {
            const raw = link.innerText.replace(/\\s+/g, ' ').trim();
            // Strip mutual-connections noise from the end
            const cleaned = raw.replace(/\\s+Message\\s+.+$/, '').trim();
            // Name is text before the connection-degree badge ("• 1st / 2nd / 3rd")
            const degreeIdx = cleaned.search(/\\s*•\\s*\\d+(?:st|nd|rd|th)\\b/);
            const name = degreeIdx > 0 ? cleaned.slice(0, degreeIdx).trim() : cleaned;
            return {
                url: link.href.split('?')[0].split('#')[0].replace(/\\/$/, ''),
                name: name,
                headline: '',
                location: cleaned,  // full blob — contains location for SEA check
            };
        });
    }

    for (const card of cards.slice(0, limit)) {
        // Profile link
        const link = card.querySelector('a[href*="/in/"]');
        if (!link) continue;
        const slug = link.href.match(/\\/in\\/([^/?#]+)/)?.[1];
        if (!slug) continue;

        // Name — try multiple selectors then fall back to link text.
        let name = '';
        for (const sel of [
            '.entity-result__title-text',
            'span[aria-hidden="true"]',
            '.search-result__result-link',
        ]) {
            const el = card.querySelector(sel);
            if (el) { name = el.innerText.replace(/\\s+/g, ' ').trim(); break; }
        }
        if (!name) name = link.innerText.replace(/\\s+/g, ' ').trim();

        // Headline (role / company line)
        let headline = '';
        for (const sel of [
            '.entity-result__primary-subtitle',
            '.subline-level-1',
            '.search-result__snippets',
        ]) {
            const el = card.querySelector(sel);
            if (el) { headline = el.innerText.replace(/\\s+/g, ' ').trim(); break; }
        }

        // Location
        let location = '';
        for (const sel of [
            '.entity-result__secondary-subtitle',
            '.subline-level-2',
        ]) {
            const el = card.querySelector(sel);
            if (el) { location = el.innerText.replace(/\\s+/g, ' ').trim(); break; }
        }

        results.push({
            url: 'https://www.linkedin.com/in/' + slug,
            name,
            headline,
            location,
        });
    }
    return results;
}
"""


def _extract_search_results(page: Any, limit: int = 10) -> list[dict]:
    """Return structured result data from the current LinkedIn search page."""
    try:
        results = page.evaluate(_EXTRACT_JS, limit)
        return results if isinstance(results, list) else []
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _is_sea_location(location: str) -> bool:
    text = f" {location.lower()} "
    return any(term in text for term in _SEA_TERMS)


def _is_ai_competitor(headline: str) -> bool:
    text = headline.lower()
    return any(term in text for term in _AI_COMPETITOR_TERMS)


def _name_matches(result_name: str, search_name: str) -> bool:
    """Return True if result_name plausibly refers to the same person."""
    def tokens(s: str) -> set[str]:
        return set(re.sub(r"[^a-z\s]", "", s.lower()).split())

    search_tokens = tokens(search_name)
    result_tokens = tokens(result_name)
    if not search_tokens or not result_tokens:
        return False
    # Require all search-name tokens to appear in the result name.
    return search_tokens.issubset(result_tokens)


def _score_result(
    result: dict,
    search_name: str,
    expected_company: str,
) -> Optional[int]:
    """Return a confidence score for this result, or None to reject it."""
    # Hard reject: name doesn't match at all.
    if not _name_matches(result["name"], search_name):
        return None

    # Hard reject: outside SEA (per CLAUDE.md — Dubai incident).
    if not _is_sea_location(result["location"]):
        return None

    # Hard reject: AI competitor / provider in headline.
    if _is_ai_competitor(result["headline"]):
        return None

    score = _MIN_CONFIDENCE_SCORE  # passed SEA check

    # Bonus: company name appears in headline or location blob (fallback mode
    # puts the full card text in location when headline is unavailable).
    if expected_company:
        haystack = (result["headline"] or result["location"]).lower()
        if expected_company.lower() in haystack:
            score += 20

    # Bonus: exact name match (not just subset).
    if result["name"].lower() == search_name.lower():
        score += 10

    return score


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_for_profile(name: str, company: str = "") -> Optional[str]:
    """Search LinkedIn by name, validate results, return best-match URL or None.

    Validation requires:
    - Name tokens from ``name`` appear in the result's displayed name.
    - Result location is in Malaysia / SEA.
    - Headline does not indicate an AI-competitor company.

    Returns None if no result meets the confidence threshold.
    Raises ``rate_limiter.RateLimitExceeded`` if today's budget is used up.
    """
    rate_limiter.check("name_search")

    query = name.strip()
    encoded = urllib.parse.quote(query)
    url = f"https://www.linkedin.com/search/results/people/?keywords={encoded}"
    target = f"name_search:{query}"

    try:
        with linkedin_session(headless=True) as page:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2_500)
            results = _extract_search_results(page, limit=10)

        if not results:
            audit.log("name_search", target=target, success=False,
                      error_message="no_results_extracted")
            return None

        # Score every result; collect valid candidates.
        candidates: list[tuple[int, dict]] = []
        for r in results:
            score = _score_result(r, query, company)
            if score is not None:
                candidates.append((score, r))

        if not candidates:
            audit.log("name_search", target=target, success=False,
                      error_message=f"no_confident_match (extracted {len(results)})")
            return None

        candidates.sort(key=lambda x: -x[0])
        best_score, best = candidates[0]
        profile_url = _normalize_profile_url(best["url"])

        audit.log("name_search", target=target, success=profile_url is not None,
                  error_message=None if profile_url else "url_normalise_failed")
        return profile_url

    except Exception as exc:  # noqa: BLE001
        audit.log("name_search", target=target, success=False,
                  error_message=f"{type(exc).__name__}: {exc}")
        raise
