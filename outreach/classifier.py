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


_ARCHITECTURE_TERMS = frozenset([
    "architecture", "infrastructure", "how is it built", "how does it work technically",
    "what technology", "tech stack", "data handling", "data privacy", "data security",
    "where is data stored", "integration", "api", "lms", "learning management",
    "how does the ai", "what model", "gpt", "openai", "which llm", "built on",
    "security", "compliance", "gdpr", "pdpa", "iso", "soc 2",
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

_MEETING_CONFIRMED_TERMS = frozenset([
    "sounds good", "works for me", "i'm free", "im free", "can do",
    "let's do", "lets do", "that works", "perfect", "confirmed",
    "see you then", "see you there", "i'll be there", "ill be there",
    "looking forward", "locked in", "put it in", "done deal",
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

    if any(term in lower for term in _ARCHITECTURE_TERMS):
        return "architecture_question"

    if any(term in lower for term in _AGGRESSIVE_TERMS):
        return "aggressive"

    # Meeting confirmed: has both a confirmation phrase AND a time reference
    has_confirmation = any(term in lower for term in _MEETING_CONFIRMED_TERMS)
    has_time = any(term in lower for term in _TIME_INDICATORS)
    if has_confirmation and has_time:
        return "meeting_confirmed"

    if any(term in lower for term in _NEGATIVE_TERMS):
        return "not_interested"

    if any(term in lower for term in _PRICING_TERMS):
        return "pricing"

    if any(term in lower for term in _MEETING_TERMS):
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
