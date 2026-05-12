"""Shared keyword sets for prospect filtering and validation.

Two distinct domains use AI-competitor terms with different vocabularies:

- ``BNI_AI_COMPETITOR_TERMS`` is matched against concatenated BNI prospect
  fields (name, company, profession, area, city, category). Broader catch-all
  language ("automation", "machine learning") because BNI entries describe
  the business in plain words.
- ``LINKEDIN_HEADLINE_AI_COMPETITOR_TERMS`` is matched against LinkedIn
  search-result headlines. Uses more specific positioning phrases ("ai
  solutions", "ai automation") because headlines are marketing copy.

Keeping the two lists distinct prevents accidental over-exclusion when
either list is edited.
"""

from __future__ import annotations


# Southeast Asia / Malaysia location markers. Shared between the BNI
# dry-run filter (matches prospect city/area) and LinkedIn search-result
# validation (matches result location text). Superset is safe for both.
SEA_LOCATION_TERMS: frozenset[str] = frozenset([
    "malaysia", "kuala lumpur", "kuala", " kl ", "selangor", "penang",
    "johor", "melaka", "perak", "sabah", "sarawak", "putrajaya",
    "petaling", "puchong", "subang", "cheras", "ampang", "klang",
    "singapore", "indonesia", "jakarta", "thailand", "bangkok",
    "philippines", "manila", "vietnam", "ho chi minh", "hanoi",
    "myanmar", "brunei", "cambodia",
])


# Category/profession terms that mark a BNI prospect as a likely fit
# (marketing, HR, training, professional services). Used for dry-run
# pre-validation scoring.
SUITABLE_TERMS: tuple[str, ...] = (
    "advertising",
    "marketing",
    "branding",
    "human resources",
    "employment",
    "consulting",
    "business consultant",
    "training",
    "education",
    "professional services",
)


# AI-competitor markers in BNI prospect fields. Padded matching: callers
# wrap the haystack in spaces so " ai " catches the standalone token without
# matching words like "details" or "stairs".
BNI_AI_COMPETITOR_TERMS: tuple[str, ...] = (
    " ai ",
    "artificial intelligence",
    "automation",
    "chatbot",
    "agentic",
    "machine learning",
    "data scientist",
    "ai agent",
    "generative ai",
)


# AI-competitor markers in LinkedIn search-result headlines. More specific
# positioning phrases than the BNI list.
LINKEDIN_HEADLINE_AI_COMPETITOR_TERMS: frozenset[str] = frozenset([
    "artificial intelligence company", "ai automation", "chatbot vendor",
    "agentic", "generative ai", "ai agent", "llm", "ai training provider",
    "ai solutions", "ai startup",
])
