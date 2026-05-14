"""Per-prospect research: gather LinkedIn data, clean it, store raw JSON.

The LLM-driven *synthesis* of a brief from the raw data happens
interactively in Claude Code (see prompts/research_brief.md). This module
just handles the data plumbing: scrape via Phase 2 tools, clean
boilerplate, persist. Drafting should prefer useful recent posts/engagement as
the opener hook, then fall back to profile/company/category and market-truth
hooks when recent activity is missing or weak.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Optional

from outreach.db.connection import get_connection
from outreach.linkedin.profile import ProfileData, read_profile


# LinkedIn's screen-reader markup adds a header to every post:
#   "Feed post number N\n<name>\n<name>\n• You\nVerified...\n
#    <headline>\n<headline>\nNd •\n \nN days ago • Visible to anyone..."
# We strip everything up to and including "Visible to anyone..." which
# always immediately precedes the actual post body.
_POST_HEADER_RE = re.compile(
    r"\bVisible to anyone(?:\s+on or off LinkedIn)?\s*",
    re.IGNORECASE,
)


def clean_post_text(raw: str) -> str:
    """Strip LinkedIn screen-reader boilerplate from a post's inner_text."""
    match = _POST_HEADER_RE.search(raw)
    if match:
        return raw[match.end():].strip()
    return raw.strip()


def gather_research(prospect_id: int) -> dict:
    """Pull LinkedIn profile + posts for ``prospect_id`` and persist raw data.

    Requires the prospect to have a ``linkedin_url`` already (run
    ``linkedin-search`` or ``enrich`` first).

    Returns the cleaned research dict.
    """
    conn = get_connection()
    try:
        prospect = conn.execute(
            "SELECT id, name, company, linkedin_url FROM prospects WHERE id = ?",
            (prospect_id,),
        ).fetchone()
        if not prospect:
            raise ValueError(f"Prospect {prospect_id} not found")
        url = prospect["linkedin_url"]
        if not url:
            raise ValueError(
                f"Prospect {prospect_id} ({prospect['name']}) has no LinkedIn URL. "
                "Run `outreach enrich <id>` first."
            )

        print(f"📡 Reading {prospect['name']} ({prospect['company']}) → {url}")
        raw: ProfileData = read_profile(url, max_posts=5)

        # Clean activity items; drop very short fragments.
        cleaned_activity = []
        for item in (raw.get("activity") or []):
            cleaned = clean_post_text(item["text"])
            if len(cleaned) >= 30:
                cleaned_activity.append({"type": item["type"], "text": cleaned})
        raw["activity"] = cleaned_activity

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO research (prospect_id, raw_json, gathered_at)
            VALUES (?, ?, ?)
            ON CONFLICT(prospect_id) DO UPDATE SET
                raw_json = excluded.raw_json,
                gathered_at = excluded.gathered_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (prospect_id, json.dumps(raw, ensure_ascii=False), now),
        )
        conn.commit()
        print(
            f"✅ Saved: {len(cleaned_activity)} activity items, "
            f"headline={raw.get('headline')!r}"
        )
        return raw
    finally:
        conn.close()


def get_research(prospect_id: int) -> Optional[dict]:
    """Return everything we know about a prospect — basic info + research.

    Returns ``None`` if the prospect doesn't exist.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT p.id, p.name, p.company, p.profession, p.area, p.city,
                   p.bni_chapter, p.category, p.linkedin_url,
                   r.raw_json, r.brief_md, r.gathered_at, r.brief_at
            FROM prospects p
            LEFT JOIN research r ON r.prospect_id = p.id
            WHERE p.id = ?
            """,
            (prospect_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "company": row["company"],
            "profession": row["profession"],
            "area": row["area"],
            "city": row["city"],
            "bni_chapter": row["bni_chapter"],
            "category": row["category"],
            "linkedin_url": row["linkedin_url"],
            "raw": json.loads(row["raw_json"]) if row["raw_json"] else None,
            "brief_md": row["brief_md"],
            "gathered_at": row["gathered_at"],
            "brief_at": row["brief_at"],
        }
    finally:
        conn.close()


def save_brief(prospect_id: int, brief_md: str) -> None:
    """Save a synthesized brief into ``research.brief_md``."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO research (prospect_id, brief_md, brief_at)
            VALUES (?, ?, ?)
            ON CONFLICT(prospect_id) DO UPDATE SET
                brief_md = excluded.brief_md,
                brief_at = excluded.brief_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (prospect_id, brief_md, now),
        )
        conn.commit()
    finally:
        conn.close()


def enrich(prospect_id: int) -> Optional[str]:
    """Run LinkedIn profile enrichment and update prospects.linkedin_url.

    Returns the URL if found, None otherwise. Updates enrichment_status.
    """
    from outreach.linkedin.search import search_for_profile  # local to avoid circular

    conn = get_connection()
    try:
        prospect = conn.execute(
            "SELECT id, name, company FROM prospects WHERE id = ?",
            (prospect_id,),
        ).fetchone()
        if not prospect:
            raise ValueError(f"Prospect {prospect_id} not found")

        url = search_for_profile(prospect["name"], prospect["company"] or "")
        now = datetime.now(timezone.utc).isoformat()
        if url:
            conn.execute(
                """
                UPDATE prospects
                SET linkedin_url = ?, enrichment_status = 'found',
                    enrichment_attempted_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (url, now, prospect_id),
            )
        else:
            conn.execute(
                """
                UPDATE prospects
                SET enrichment_status = 'not_found',
                    enrichment_attempted_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (now, prospect_id),
            )
        conn.commit()
        return url
    finally:
        conn.close()
