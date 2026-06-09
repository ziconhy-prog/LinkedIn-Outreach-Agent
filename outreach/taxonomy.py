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


# Malaysia-only location markers. Used for strict candidate selection
# and LinkedIn match validation — prevents false matches with same-named
# people based in Singapore/Indonesia/etc.
MY_LOCATION_TERMS: frozenset[str] = frozenset([
    "malaysia",
    # States
    "selangor", "penang", "pulau pinang", "johor", "melaka", "malacca",
    "perak", "kedah", "kelantan", "terengganu", "pahang", "perlis",
    "negeri sembilan", "sabah", "sarawak", "labuan", "putrajaya",
    # Major cities / districts
    "kuala lumpur", " kl ", "petaling jaya", "petaling", "shah alam",
    "puchong", "subang", "cheras", "ampang", "klang", "kajang",
    "bangsar", "damansara", "mont kiara", "cyberjaya",
    "johor bahru", "iskandar", "skudai",
    "georgetown", "bayan lepas", "bukit mertajam",
    "ipoh", "kota kinabalu", "kuching", "miri", "sibu",
    "alor setar", "kuantan", "kota bharu", "seremban",
    "melaka tengah",
])


# Wider SEA / Malaysia location markers. Kept for the legacy dry-run
# command which intentionally surfaces broader matches; the live pipeline
# uses MY_LOCATION_TERMS exclusively.
SEA_LOCATION_TERMS: frozenset[str] = frozenset([
    *MY_LOCATION_TERMS,
    "singapore", "indonesia", "jakarta", "thailand", "bangkok",
    "philippines", "manila", "vietnam", "ho chi minh", "hanoi",
    "myanmar", "brunei", "cambodia",
])


# Category/profession terms that mark a BNI prospect as a likely fit.
# Covers marketing/HR/training roles AND software/tech companies (the bulk
# of this BNI chapter) who need AI upskilling for their teams.
SUITABLE_TERMS: tuple[str, ...] = (
    # Service / people-focused roles
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
    "recruitment",
    # Tech/software companies — dominant in this BNI dataset
    "software",
    "it services",
    "computer",
    "technology",
    "digital services",
    "web development",
    "app development",
    "system integrat",
    "cloud",
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
