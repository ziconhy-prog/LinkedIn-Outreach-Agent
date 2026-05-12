"""CLI entry point. Run with: python -m outreach <command>."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from outreach import __version__, drafting, rate_limiter, research, telegram_bot, telegram_client
from outreach.config import DB_PATH, PROJECT_ROOT, ensure_dirs
from outreach.db.connection import get_connection
from outreach.ingest.bni_parser import parse_and_load
from outreach.ingest.voice_samples import (
    load_voice_samples,
    verify as verify_voice_samples,
)
from outreach.linkedin.profile import read_profile
from outreach.linkedin.search import search_for_profile
from outreach.linkedin.session import check_session, perform_login


# ---------- Phase 1 commands ----------

def cmd_init_db(_: argparse.Namespace) -> int:
    """Create the database file (if absent) and apply the schema."""
    ensure_dirs()
    schema_path = Path(__file__).parent / "db" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema_sql)
        conn.commit()
        print(f"✅ Database initialized at {DB_PATH}")
    finally:
        conn.close()
    return 0


def cmd_parse_bni(args: argparse.Namespace) -> int:
    """Parse the BNI PDF at ``args.pdf_path`` and load into prospects."""
    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_path}")
        return 1
    parse_and_load(pdf_path)
    return 0


def cmd_voice_samples(_: argparse.Namespace) -> int:
    """Verify the voice samples folder loads cleanly."""
    return 0 if verify_voice_samples() else 1


# ---------- Phase 4 setup commands (Telegram approval cockpit) ----------

def cmd_telegram_status(_: argparse.Namespace) -> int:
    """Check whether Telegram bot settings are present and valid."""
    try:
        bot = telegram_client.get_me()
    except telegram_client.TelegramConfigError as exc:
        print(f"❌ {exc}")
        print()
        print("To connect Telegram:")
        print("1. Open Telegram and talk to @BotFather.")
        print("2. Create a bot and copy the token into .env as TELEGRAM_BOT_TOKEN.")
        print("3. Talk to @userinfobot and copy your numeric ID into .env as TELEGRAM_OPERATOR_USER_ID.")
        print("4. Run this command again.")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Telegram check failed: {type(exc).__name__}: {exc}")
        return 1

    print("✅ Telegram bot token works")
    print(f"Bot: @{bot.get('username', '(unknown)')} ({bot.get('first_name', 'unknown')})")
    print("Operator user ID is configured")
    print("No LinkedIn messages were sent.")
    return 0


def cmd_telegram_poll(args: argparse.Namespace) -> int:
    """Start the Telegram operator polling loop (Ctrl-C to stop)."""
    try:
        telegram_client.require_config()
    except telegram_client.TelegramConfigError as exc:
        print(f"❌ {exc}")
        return 1
    telegram_bot.run_polling_loop(once=args.once)
    return 0


def cmd_telegram_test(_: argparse.Namespace) -> int:
    """Send a test message to the configured operator chat."""
    text = (
        "SkillTrainer AI outreach bot test.\n\n"
        "Telegram is connected. This is only a test message. "
        "No LinkedIn messages were sent."
    )
    try:
        telegram_client.send_operator_message(text)
    except telegram_client.TelegramConfigError as exc:
        print(f"❌ {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Telegram test failed: {type(exc).__name__}: {exc}")
        return 1
    print("✅ Test message sent to Telegram")
    print("No LinkedIn messages were sent.")
    return 0


# ---------- Phase 2 commands (LinkedIn read-only) ----------

def cmd_linkedin_login(_: argparse.Namespace) -> int:
    """One-time login: open browser, operator logs in, session is saved."""
    return 0 if perform_login() else 1


def cmd_linkedin_status(_: argparse.Namespace) -> int:
    """Verify the saved session is still logged in."""
    print("🔍 Checking LinkedIn session...")
    if check_session():
        print("✅ Session is logged in")
        _print_rate_limit_status()
        return 0
    print("❌ Session is not logged in. Run `linkedin-login` to set it up.")
    return 1


def cmd_linkedin_search(args: argparse.Namespace) -> int:
    """Search LinkedIn by name (+ optional company) and print profile URL."""
    try:
        url = search_for_profile(args.name, args.company or "")
    except rate_limiter.RateLimitExceeded as exc:
        print(f"⏸  {exc}")
        return 1
    if url:
        print(url)
        return 0
    print("(no profile found)")
    return 2


def cmd_linkedin_profile(args: argparse.Namespace) -> int:
    """Read a LinkedIn profile URL and print headline + last 5 posts."""
    try:
        data = read_profile(args.url, max_posts=args.posts)
    except rate_limiter.RateLimitExceeded as exc:
        print(f"⏸  {exc}")
        return 1
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    print(f"Name:      {data.get('name') or '(unknown)'}")
    print(f"Headline:  {data.get('headline') or '(unknown)'}")
    print(f"Location:  {data.get('location') or '(unknown)'}")
    posts = data.get("posts") or []
    print(f"\nLast {len(posts)} posts:")
    for i, post in enumerate(posts, 1):
        preview = post.replace("\n", " ").strip()
        if len(preview) > 200:
            preview = preview[:200] + "…"
        print(f"  {i}. {preview}")
    return 0


def _print_rate_limit_status() -> None:
    status = rate_limiter.status()
    print("\nToday's rate-limit budget:")
    for budget, info in status.items():
        print(f"  {budget:30s} {info['used']:3d} / {info['cap']:3d}")


# ---------- Phase 3 commands (research + drafting) ----------

def cmd_enrich(args: argparse.Namespace) -> int:
    """Search LinkedIn for a prospect and update their linkedin_url."""
    try:
        url = research.enrich(args.prospect_id)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except rate_limiter.RateLimitExceeded as exc:
        print(f"⏸  {exc}")
        return 1
    if url:
        print(f"✅ {url}")
        return 0
    print("(no profile found — marked enrichment_status='not_found')")
    return 2


def cmd_research(args: argparse.Namespace) -> int:
    """Gather LinkedIn profile + posts for a prospect, save raw research."""
    try:
        research.gather_research(args.prospect_id)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except rate_limiter.RateLimitExceeded as exc:
        print(f"⏸  {exc}")
        return 1
    return 0


def cmd_show_research(args: argparse.Namespace) -> int:
    """Print everything we have for a prospect: basic info, raw, brief, drafts."""
    data = research.get_research(args.prospect_id)
    if not data:
        print(f"❌ Prospect {args.prospect_id} not found.")
        return 1
    print(f"# {data['name']} ({data['id']})")
    print(f"Company:   {data['company']}")
    print(f"Profession:{data['profession']}")
    print(f"Area:      {data['area']}  /  City: {data['city']}")
    print(f"BNI:       {data['bni_chapter']}")
    print(f"Category:  {data['category']}")
    print(f"LinkedIn:  {data['linkedin_url']}")
    print()
    print(f"Gathered:  {data['gathered_at']}")
    print(f"Brief at:  {data['brief_at']}")
    print()
    if data["raw"]:
        print("## Raw research")
        print(json.dumps(data["raw"], indent=2, ensure_ascii=False))
        print()
    if data["brief_md"]:
        print("## Brief")
        print(data["brief_md"])
        print()
    drafts = drafting.get_drafts_for_prospect(args.prospect_id)
    if drafts:
        print("## Messages")
        for d in drafts:
            print(f"  [{d['id']}] {d['role']:9s} {d['status']:8s} "
                  f"{d['created_at']}")
            print(f"      {d['content']}")
    return 0


def cmd_prompt_brief(args: argparse.Namespace) -> int:
    """Print the full prompt for synthesizing a brief, ready for Claude Code."""
    data = research.get_research(args.prospect_id)
    if not data:
        print(f"❌ Prospect {args.prospect_id} not found.")
        return 1
    if not data["raw"]:
        print(f"❌ No research data yet. Run `outreach research {args.prospect_id}` first.")
        return 1

    template = (PROJECT_ROOT / "prompts" / "research_brief.md").read_text(
        encoding="utf-8"
    )
    print(template)
    print("\n---\n")
    print("## Prospect dossier")
    raw = data["raw"]
    # Prefer the typed activity list; fall back to flat posts for old DB rows.
    linkedin_data = dict(raw)
    if "activity" not in linkedin_data and "posts" in linkedin_data:
        linkedin_data["activity"] = [
            {"type": "post", "text": p} for p in linkedin_data["posts"]
        ]
    dossier = {
        "name": data["name"],
        "company": data["company"],
        "profession": data["profession"],
        "area": data["area"],
        "city": data["city"],
        "bni_chapter": data["bni_chapter"],
        "category": data["category"],
        "linkedin": linkedin_data,
    }
    print("```json")
    print(json.dumps(dossier, indent=2, ensure_ascii=False))
    print("```")
    return 0


def cmd_prompt_opener(args: argparse.Namespace) -> int:
    """Print the full prompt for drafting an opener, ready for Claude Code."""
    data = research.get_research(args.prospect_id)
    if not data:
        print(f"❌ Prospect {args.prospect_id} not found.")
        return 1
    if not data["brief_md"]:
        print(
            f"❌ No brief yet. Generate one via `outreach prompt-brief "
            f"{args.prospect_id}` then save with `save-brief`."
        )
        return 1

    template = (PROJECT_ROOT / "prompts" / "opener.md").read_text(encoding="utf-8")
    print(template)
    print("\n---\n")
    print("## Prospect basics")
    print(f"- Name: {data['name']}")
    print(f"- Company: {data['company']}")
    if data["raw"] and data["raw"].get("headline"):
        print(f"- Headline: {data['raw']['headline']}")
    print()
    print("## Research brief")
    print(data["brief_md"])
    print()
    samples = load_voice_samples()
    print(f"## Voice samples ({len(samples)} from voice-samples/)")
    for i, sample in enumerate(samples, 1):
        print(f"\n### Sample {i}")
        print(sample)
    return 0


def cmd_prompt_brief_mini(args: argparse.Namespace) -> int:
    """Print ONLY the prospect dossier JSON. Assumes the template + rules
    are already in the caller's context from an earlier `prompt-brief` run.
    """
    data = research.get_research(args.prospect_id)
    if not data:
        print(f"❌ Prospect {args.prospect_id} not found.")
        return 1
    if not data["raw"]:
        print(f"❌ No research data yet. Run `outreach research {args.prospect_id}` first.")
        return 1
    dossier = {
        "name": data["name"],
        "company": data["company"],
        "profession": data["profession"],
        "area": data["area"],
        "city": data["city"],
        "bni_chapter": data["bni_chapter"],
        "category": data["category"],
        "linkedin": data["raw"],
    }
    print(json.dumps(dossier, indent=2, ensure_ascii=False))
    return 0


def cmd_prompt_opener_mini(args: argparse.Namespace) -> int:
    """Print ONLY prospect basics + research brief. Assumes the template,
    voice rules, and 20 voice samples are already in the caller's context
    from an earlier `prompt-opener` run.
    """
    data = research.get_research(args.prospect_id)
    if not data:
        print(f"❌ Prospect {args.prospect_id} not found.")
        return 1
    if not data["brief_md"]:
        print(
            f"❌ No brief yet. Run `outreach prompt-brief {args.prospect_id}` "
            f"and save with `save-brief` first."
        )
        return 1
    print("## Prospect basics")
    print(f"- Name: {data['name']}")
    print(f"- Company: {data['company']}")
    if data["raw"] and data["raw"].get("headline"):
        print(f"- Headline: {data['raw']['headline']}")
    print()
    print("## Research brief")
    print(data["brief_md"])
    return 0


def cmd_save_brief(args: argparse.Namespace) -> int:
    """Save a brief from a file path into the prospect's research record."""
    text = Path(args.file).read_text(encoding="utf-8").strip()
    if not text:
        print("❌ Brief file is empty.")
        return 1
    research.save_brief(args.prospect_id, text)
    print(f"✅ Brief saved for prospect {args.prospect_id} ({len(text)} chars)")
    return 0


def cmd_save_opener(args: argparse.Namespace) -> int:
    """Save an opener draft from a file path; creates thread + message draft."""
    text = Path(args.file).read_text(encoding="utf-8").strip()
    if not text:
        print("❌ Opener file is empty.")
        return 1
    msg_id = drafting.save_opener(args.prospect_id, text)
    print(f"✅ Opener saved as message {msg_id} (status=draft, awaiting Telegram approval)")
    return 0


_SUITABLE_TERMS = (
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

_AI_COMPETITOR_TERMS = (
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

_TARGET_GEO_TERMS = (
    "malaysia",
    "kuala",
    "selangor",
    "petaling",
    "johor",
    "melaka",
    "penang",
    "perak",
    "sabah",
    "sarawak",
    "singapore",
)


def _haystack(row: dict) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("name", "company", "profession", "area", "city", "category")
    ).lower()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    padded = f" {text} "
    return any(term in padded for term in terms)


def _candidate_score(row: dict) -> int:
    text = _haystack(row)
    score = 0
    for term in _SUITABLE_TERMS:
        if term in text:
            score += 10
    for term in _TARGET_GEO_TERMS:
        if term in text:
            score += 4
    if "branding" in text or "marketing" in text:
        score += 6
    if "human resources" in text or "training" in text:
        score += 5
    return score


def cmd_dry_run_batch(args: argparse.Namespace) -> int:
    """Print a local pre-validation batch from the prospect database.

    This does not touch LinkedIn and does not send messages. It only surfaces
    likely-fit local candidates and prints the research-led workflow to follow.
    Each candidate still needs LinkedIn result-list validation before drafting.
    """
    limit = args.limit
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, company, profession, area, city, category,
                   enrichment_status, linkedin_url
            FROM prospects
            WHERE do_not_contact = 0
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    candidates = []
    for raw in rows:
        row = dict(raw)
        text = _haystack(row)
        if _contains_any(text, _AI_COMPETITOR_TERMS):
            continue
        if not _contains_any(text, _SUITABLE_TERMS):
            continue
        if not _contains_any(text, _TARGET_GEO_TERMS):
            continue
        candidates.append((_candidate_score(row), row))

    candidates.sort(key=lambda item: (-item[0], item[1]["id"]))
    selected = candidates[:limit]

    if args.markdown:
        print(f"# Dry-Run Pre-Validation Batch ({len(selected)} prospects)")
        print()
        print("Mode: dry run only. Do not send LinkedIn messages.")
        print("These are local database candidates, not validated LinkedIn matches yet.")
        print()
        print("Workflow for each prospect:")
        print()
        print("1. Search LinkedIn by name only.")
        print("2. Validate company, headline, and Malaysia/SEA location from the result list.")
        print("3. Reject uncertain matches and AI-provider/competitor profiles.")
        print("4. Open the matched profile and research visible recent posts, comments, reposts, or engagement.")
        print("5. Use a post/engagement hook only if Playwright actually captured that activity.")
        print("6. If no suitable activity exists, use profile/company/category or market-truth hook.")
        print("7. Draft opener only. No product pitch and no meeting ask in the opener.")
        print("8. Continue the simulated conversation toward SkillTrainer AI only after relevant pain appears.")
        print()
        print("## Candidates")
        print()
        for _, row in selected:
            print(f"### {row['id']}. {row['name']}")
            print()
            print(f"- Company: {row['company'] or '(unknown)'}")
            print(f"- Category: {row['category'] or '(unknown)'}")
            print(f"- Profession: {row['profession'] or '(unknown)'}")
            print(f"- Location: {row['city'] or '(unknown)'} / {row['area'] or '(unknown)'}")
            print(f"- LinkedIn status: {row['enrichment_status']}")
            if row["linkedin_url"]:
                print(f"- Stored LinkedIn: {row['linkedin_url']}")
            print("- Validation needed: yes")
            print()
        return 0

    for _, row in selected:
        compact_profession = re.sub(r"\s+", " ", row["profession"] or "").strip()
        print(
            f"{row['id']:4d}  {row['name']} | {row['company'] or '-'} | "
            f"{row['city'] or '-'} | {compact_profession}"
        )
    return 0


# ---------- Argparse wiring ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outreach",
        description=f"LinkedIn Outreach Agent v{__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Create the local database")
    p_init.set_defaults(func=cmd_init_db)

    p_bni = sub.add_parser("parse-bni", help="Parse the BNI PDF into prospects")
    p_bni.add_argument("pdf_path", help="Path to the BNI Malaysia members PDF")
    p_bni.set_defaults(func=cmd_parse_bni)

    p_voice = sub.add_parser("voice-samples", help="Verify voice samples load")
    p_voice.set_defaults(func=cmd_voice_samples)

    p_tg_status = sub.add_parser("telegram-status", help="Check Telegram bot setup")
    p_tg_status.set_defaults(func=cmd_telegram_status)

    p_tg_test = sub.add_parser("telegram-test", help="Send a Telegram test message")
    p_tg_test.set_defaults(func=cmd_telegram_test)

    p_tg_poll = sub.add_parser("telegram-poll", help="Start the Telegram operator polling loop")
    p_tg_poll.add_argument(
        "--once",
        action="store_true",
        help="Fetch pending updates once and exit (useful for testing)",
    )
    p_tg_poll.set_defaults(func=cmd_telegram_poll)

    p_login = sub.add_parser("linkedin-login", help="One-time LinkedIn login")
    p_login.set_defaults(func=cmd_linkedin_login)

    p_status = sub.add_parser("linkedin-status", help="Check LinkedIn session")
    p_status.set_defaults(func=cmd_linkedin_status)

    p_search = sub.add_parser("linkedin-search", help="Find a profile URL by name")
    p_search.add_argument("name", help="Person's full name")
    p_search.add_argument("company", nargs="?", default="", help="Company (optional)")
    p_search.set_defaults(func=cmd_linkedin_search)

    p_profile = sub.add_parser("linkedin-profile", help="Read a profile URL")
    p_profile.add_argument("url", help="LinkedIn profile URL")
    p_profile.add_argument("--posts", type=int, default=5, help="Posts to read (default 5)")
    p_profile.add_argument("--json", action="store_true", help="Output JSON")
    p_profile.set_defaults(func=cmd_linkedin_profile)

    p_enrich = sub.add_parser("enrich", help="Search LinkedIn for a prospect by ID and store URL")
    p_enrich.add_argument("prospect_id", type=int)
    p_enrich.set_defaults(func=cmd_enrich)

    p_research = sub.add_parser("research", help="Gather LinkedIn data for a prospect")
    p_research.add_argument("prospect_id", type=int)
    p_research.set_defaults(func=cmd_research)

    p_show = sub.add_parser("show-research", help="Show stored research + brief + drafts")
    p_show.add_argument("prospect_id", type=int)
    p_show.set_defaults(func=cmd_show_research)

    p_pb = sub.add_parser("prompt-brief", help="Print the prompt for generating a brief")
    p_pb.add_argument("prospect_id", type=int)
    p_pb.set_defaults(func=cmd_prompt_brief)

    p_po = sub.add_parser("prompt-opener", help="Print the prompt for drafting an opener")
    p_po.add_argument("prospect_id", type=int)
    p_po.set_defaults(func=cmd_prompt_opener)

    p_pbm = sub.add_parser(
        "prompt-brief-mini",
        help="Print only the dossier (use after prompt-brief was run once this session)",
    )
    p_pbm.add_argument("prospect_id", type=int)
    p_pbm.set_defaults(func=cmd_prompt_brief_mini)

    p_pom = sub.add_parser(
        "prompt-opener-mini",
        help="Print only basics + brief (use after prompt-opener was run once)",
    )
    p_pom.add_argument("prospect_id", type=int)
    p_pom.set_defaults(func=cmd_prompt_opener_mini)

    p_sb = sub.add_parser("save-brief", help="Save a brief from a file")
    p_sb.add_argument("prospect_id", type=int)
    p_sb.add_argument("file", help="Path to file containing the brief markdown")
    p_sb.set_defaults(func=cmd_save_brief)

    p_so = sub.add_parser("save-opener", help="Save an opener draft from a file")
    p_so.add_argument("prospect_id", type=int)
    p_so.add_argument("file", help="Path to file containing the opener text")
    p_so.set_defaults(func=cmd_save_opener)

    p_dry = sub.add_parser(
        "dry-run-batch",
        help="Suggest a local pre-validation batch for manual dry-run testing",
    )
    p_dry.add_argument("--limit", type=int, default=5, help="Number of candidates")
    p_dry.add_argument(
        "--markdown",
        action="store_true",
        help="Print a markdown checklist with candidate details",
    )
    p_dry.set_defaults(func=cmd_dry_run_batch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
