"""Full automated prospecting pipeline.

Triggered by Telegram message. Runs:
  1. Pull candidates from BNI list
  2. Search LinkedIn by name
  3. Validate match (location, headline, not competitor)
  4. Scrape profile + posts
  5. Generate research brief via Claude API
  6. Draft opener via Claude API
  7. Save as draft message in DB, queue for Telegram approval

Reports progress back to Telegram.
"""

from __future__ import annotations

import json
from pathlib import Path

import anthropic

from outreach.config import ANTHROPIC_API_KEY, PROJECT_ROOT
from outreach.db.connection import get_connection
from outreach import audit, drafting, rate_limiter
from outreach.ingest.voice_samples import load_voice_samples
from outreach.linkedin.search import search_for_profile
from outreach.linkedin.profile import read_profile
from outreach.linkedin.humanlike import LinkedInChallengeDetected
from outreach.taxonomy import BNI_AI_COMPETITOR_TERMS, MY_LOCATION_TERMS, SUITABLE_TERMS

_RESEARCH_BRIEF_PROMPT = (PROJECT_ROOT / "prompts" / "research_brief.md").read_text(encoding="utf-8")
_OPENER_PROMPT = (PROJECT_ROOT / "prompts" / "opener.md").read_text(encoding="utf-8")
_VOICE_SPEC = (PROJECT_ROOT / "prompts" / "voice.md").read_text(encoding="utf-8")

def _load_humanize_rules() -> str:
    skill = PROJECT_ROOT / "humanize" / "SKILL.md"
    patterns = PROJECT_ROOT / "humanize" / "overused-ai-patterns.md"
    parts = []
    for path in (skill, patterns):
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else ""

_HUMANIZE_RULES = _load_humanize_rules()


# ---------------------------------------------------------------------------
# Candidate selection (same logic as dry-run-batch)
# ---------------------------------------------------------------------------

def _haystack(row: dict) -> str:
    return " ".join(
        str(row.get(k) or "") for k in ("name", "company", "profession", "area", "city", "category")
    ).lower()


def _contains_any(text: str, terms) -> bool:
    padded = f" {text} "
    return any(t in padded for t in terms)


def _pull_candidates(limit: int) -> list[dict]:
    """Return up to limit BNI prospects that pass the pre-validation filter."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, company, profession, area, city, category,
                   enrichment_status, linkedin_url
            FROM prospects
            WHERE do_not_contact = 0
              AND enrichment_status = 'pending'
              AND id NOT IN (SELECT DISTINCT prospect_id FROM threads)
            ORDER BY id ASC
            LIMIT 100
            """
        ).fetchall()
    finally:
        conn.close()

    candidates = []
    for raw in rows:
        row = dict(raw)
        text = _haystack(row)
        if _contains_any(text, BNI_AI_COMPETITOR_TERMS):
            continue
        if not _contains_any(text, SUITABLE_TERMS):
            continue
        if not _contains_any(text, MY_LOCATION_TERMS):
            continue
        candidates.append(row)
        if len(candidates) >= limit:
            break
    return candidates


# ---------------------------------------------------------------------------
# Research brief generation
# ---------------------------------------------------------------------------

def _generate_brief(prospect: dict, profile_data: dict) -> str:
    """Use Claude API to synthesise a research brief from raw profile data."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    dossier = {
        "bni_info": {
            "name": prospect["name"],
            "company": prospect.get("company", ""),
            "profession": prospect.get("profession", ""),
            "area": prospect.get("area", ""),
            "city": prospect.get("city", ""),
            "category": prospect.get("category", ""),
        },
        "linkedin": {
            "headline": profile_data.get("headline", ""),
            "location": profile_data.get("location", ""),
            "activity": profile_data.get("activity", []),
        },
    }

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=[{"type": "text", "text": _RESEARCH_BRIEF_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": json.dumps(dossier, ensure_ascii=False)}],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Opener generation
# ---------------------------------------------------------------------------

def _generate_opener(prospect: dict, brief: str, voice_samples: list[str]) -> str:
    """Use Claude API to draft an opener in Zico's voice."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    samples_text = "\n\n---\n\n".join(voice_samples[:10]) if voice_samples else ""

    user_content = f"""
Prospect info:
Name: {prospect['name']}
Company: {prospect.get('company', '')}
Headline: {prospect.get('headline', '')}
Location: {prospect.get('location') or prospect.get('city') or prospect.get('area') or 'Malaysia'}

Research brief:
{brief}

Voice samples (write exactly like this):
{samples_text}
""".strip()

    system = f"{_OPENER_PROMPT}\n\n{_VOICE_SPEC}\n\n{_HUMANIZE_RULES}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        temperature=0.7,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Save to DB
# ---------------------------------------------------------------------------

def _save_to_db(prospect: dict, linkedin_url: str, brief: str, opener: str) -> int:
    """Enrich prospect, save brief and opener. Returns message ID."""
    conn = get_connection()
    try:
        # Update linkedin_url and enrichment status
        conn.execute(
            "UPDATE prospects SET linkedin_url = ?, enrichment_status = 'found' WHERE id = ?",
            (linkedin_url, prospect["id"]),
        )

        # Save research brief
        conn.execute(
            """
            INSERT INTO research (prospect_id, raw_json, brief_md, gathered_at, brief_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(prospect_id) DO UPDATE SET
                brief_md = excluded.brief_md,
                brief_at = excluded.brief_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (prospect["id"], "{}", brief),
        )

        # Create thread + draft message
        cur = conn.execute(
            "INSERT INTO threads (prospect_id, status) VALUES (?, 'active')",
            (prospect["id"],),
        )
        thread_id = cur.lastrowid

        cur2 = conn.execute(
            """
            INSERT INTO messages (thread_id, direction, role, content, status)
            VALUES (?, 'outbound', 'opener', ?, 'draft')
            """,
            (thread_id, opener),
        )
        message_id = cur2.lastrowid
        conn.commit()
        return message_id
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mark_not_found(prospect_id: int) -> None:
    """Mark a prospect as not_found so they're excluded from future pipeline runs."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE prospects SET enrichment_status = 'not_found' WHERE id = ?",
            (prospect_id,),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    limit: int = 3,
    notify: callable = None,
) -> dict:
    """Run the full prospecting pipeline. Returns summary dict.

    Args:
        limit: max number of new openers to generate per run.
        notify: callable(str) to send progress updates (e.g. Telegram).
    """
    def _ping(msg: str) -> None:
        if notify:
            try:
                notify(msg)
            except Exception:  # noqa: BLE001
                pass

    summary = {"searched": 0, "matched": 0, "drafted": 0, "failed": 0}

    if not ANTHROPIC_API_KEY:
        _ping("❌ ANTHROPIC_API_KEY not set. Can't generate briefs or openers.")
        return summary

    _ping(f"🔍 Pulling candidates from BNI list...")
    candidates = _pull_candidates(limit * 3)  # Pull extra to account for failed LinkedIn matches

    if not candidates:
        _ping("No new candidates found in the BNI list.")
        return summary

    voice_samples = load_voice_samples()

    for prospect in candidates:
        if summary["drafted"] >= limit:
            break

        name = prospect["name"]
        company = prospect.get("company", "")
        _ping(f"Searching LinkedIn for {name} ({company})...")

        try:
            rate_limiter.check("name_search")
            linkedin_url = search_for_profile(name, company)
        except rate_limiter.RateLimitExceeded:
            _ping("⏸ LinkedIn rate limit reached. Stopping for today.")
            break
        except LinkedInChallengeDetected as e:
            _ping(f"⚠️ LinkedIn challenge detected. Stopping: {e}")
            break
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            continue

        summary["searched"] += 1

        if not linkedin_url:
            _ping(f"No confident LinkedIn match for {name}. Skipping.")
            # Mark as not_found so this prospect is excluded from future runs.
            _mark_not_found(prospect["id"])
            continue

        # Scrape profile
        try:
            rate_limiter.check("profile_view")
            profile_data = read_profile(linkedin_url, max_posts=5)
        except rate_limiter.RateLimitExceeded:
            _ping("⏸ LinkedIn rate limit reached. Stopping for today.")
            break
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            continue

        summary["matched"] += 1

        # Add location from LinkedIn to prospect dict for opener
        prospect["headline"] = profile_data.get("headline", "")
        prospect["location"] = profile_data.get("location", "")

        # Generate brief
        try:
            brief = _generate_brief(prospect, profile_data)
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            continue

        # Generate opener
        try:
            opener = _generate_opener(prospect, brief, voice_samples)
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            continue

        # Save to DB
        try:
            message_id = _save_to_db(prospect, linkedin_url, brief, opener)
            summary["drafted"] += 1
            audit.log("prospecting_draft", target=f"prospect:{prospect['id']}", success=True)
        except Exception as exc:  # noqa: BLE001
            summary["failed"] += 1
            continue

    _ping(
        f"✅ Done.\n\n"
        f"Searched: {summary['searched']} · Matched: {summary['matched']} · "
        f"Drafted: {summary['drafted']} · Failed: {summary['failed']}\n\n"
        f"Say 'show queue' to review and send."
    )
    return summary
