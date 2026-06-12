"""Classify inbound LinkedIn messages to decide auto-reply vs Telegram escalation.

Returns one of:
  'normal'          — follows the standard conversation arc, auto-draft a reply
  'pricing'         — pricing / contract / payment question, escalate to Zico
  'not_interested'  — prospect declining or asking to stop, escalate
  'aggressive'      — hostile or DNC request, escalate immediately
  'meeting_request' — prospect suggesting a meeting, escalate for Zico to confirm
  'uncertain'       — can't classify confidently, escalate to be safe
"""

from __future__ import annotations

import re


def _matches_any(lower: str, terms: frozenset[str]) -> bool:
    """Word-boundary matching — plain substring checks misfire badly
    (e.g. 'fee' inside 'coffee', 'free on' inside 'carefree once')."""
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lower)
        for term in terms
    )


# Multi-word phrases only — single generic words ("api", "security",
# "integration") caused normal messages to be escalated as tech questions.
_ARCHITECTURE_TERMS = frozenset([
    "architecture", "infrastructure", "how is it built", "how does it work technically",
    "what technology", "tech stack", "data handling", "data privacy", "data security",
    "where is data stored", "your api", "api integration", "integrate with our",
    "learning management system", "how does the ai", "what model do you use",
    "which llm", "built on gpt", "is it gpt", "built on openai", "is it chatgpt",
    "security audit", "compliance requirement", "gdpr", "pdpa", "iso 27001", "soc 2",
])

_AGGRESSIVE_TERMS = frozenset([
    "spam", "report you", "block you", "harassment", "don't contact me again",
    "stop messaging", "remove my details",
])

_NEGATIVE_TERMS = frozenset([
    "not interested", "no thanks", "no thank you", "not for us",
    "not for me", "not relevant", "please stop", "unsubscribe",
    "don't contact", "dont contact", "leave me alone", "not looking for",
    "already have a solution", "not the right time",
])

_PRICING_TERMS = frozenset([
    "how much", "what's the price", "pricing", "cost per", "fee",
    "invoice", "quote", "quotation", "contract", "sla", "subscription fee",
    "monthly fee", "annual fee", "payment terms", "refund",
])

_MEETING_TERMS = frozenset([
    "let's meet", "lets meet", "grab coffee", "coffee sounds good",
    "happy to meet", "schedule a call", "book a time", "book a call",
    "free on", "available on", "when are you free", "what time works",
    "zoom call", "google meet", "teams call", "video call",
    "can we meet", "would love to meet", "set up a meeting",
])

# Strong confirmation phrases only — this branch triggers the automated
# location-ask + calendar booking, so weak signals ("perfect", "can do",
# "looking forward") that merely co-occur with a time word must not match.
_MEETING_CONFIRMED_TERMS = frozenset([
    "sounds good", "works for me", "i'm free", "im free",
    "let's do", "lets do", "that works", "confirmed",
    "see you then", "see you there", "i'll be there", "ill be there",
    "locked in", "done deal",
])

_TIME_INDICATORS = frozenset([
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "next week", "tomorrow", "am", "pm",
    "morning", "afternoon", "evening", "noon", "o'clock",
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
])


def classify(text: str) -> str:
    """Return classification string for an inbound message."""
    lower = text.lower()

    if _matches_any(lower, _ARCHITECTURE_TERMS):
        return "architecture_question"

    if _matches_any(lower, _AGGRESSIVE_TERMS):
        return "aggressive"

    # Meeting confirmed: has both a confirmation phrase AND a time reference
    has_confirmation = _matches_any(lower, _MEETING_CONFIRMED_TERMS)
    has_time = _matches_any(lower, _TIME_INDICATORS)
    if has_confirmation and has_time:
        return "meeting_confirmed"

    if _matches_any(lower, _NEGATIVE_TERMS):
        return "not_interested"

    if _matches_any(lower, _PRICING_TERMS):
        return "pricing"

    if _matches_any(lower, _MEETING_TERMS):
        return "meeting_request"

    return "normal"


ESCALATION_REASONS: dict[str, str] = {
    "pricing": "pricing_question",
    "not_interested": "not_interested",
    "aggressive": "aggressive_reply",
    "meeting_request": "meeting_request",
    "meeting_confirmed": "meeting_confirmed",
    "architecture_question": "architecture_question",
    "uncertain": "uncertain",
}
