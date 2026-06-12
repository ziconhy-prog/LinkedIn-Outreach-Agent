"""Live evaluation of the Telegram brain against the real Claude API.

Feeds realistic operator phrases (including multi-turn follow-ups) through
telegram_brain.handle_message with a seeded throwaway DB, spies on which
tools the brain chooses, and checks the choices make sense.

Needs ANTHROPIC_API_KEY in .env. Costs a few cents of Sonnet usage.

Run:  python tests/live_brain_eval.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Throwaway DB BEFORE importing outreach.config — but keep the real .env
# (we need the API key from it).
_TMP = tempfile.mkdtemp(prefix="outreach_eval_")
os.environ["DB_PATH"] = str(Path(_TMP) / "eval.db")
os.environ["DATA_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outreach.config import ANTHROPIC_API_KEY, PROJECT_ROOT  # noqa: E402
from outreach.db.connection import get_connection  # noqa: E402
from outreach import telegram_brain as brain  # noqa: E402

CHAT_ID = 999_001
PASS = 0
FAIL = 0
CALLS: list[tuple[str, dict]] = []


def seed_db() -> None:
    schema = (PROJECT_ROOT / "outreach" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    from outreach.db import migrations

    migrations.run()
    reset_data()


def reset_data() -> None:
    """Reset prospects/threads/messages to a known state between scenarios."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM threads")
        conn.execute("DELETE FROM research")
        conn.execute("DELETE FROM prospects")
        for pid, name, company in [
            (1, "Keith Ngai", "Ngai Logistics"),
            (2, "Xia Dan Duar", "Duar Marketing"),
            (3, "Adibah Noor", "Noor HR Consulting"),
        ]:
            conn.execute(
                "INSERT INTO prospects (id, name, company, source, source_id, city) "
                "VALUES (?, ?, ?, 'test', ?, 'Kuala Lumpur')",
                (pid, name, company, f"t{pid}"),
            )
            conn.execute(
                "INSERT INTO threads (id, prospect_id, status) VALUES (?, ?, 'queued')",
                (pid, pid),
            )
            conn.execute(
                "INSERT INTO research (prospect_id, brief_md) VALUES (?, ?)",
                (pid, f"{name} runs {company}. Cares about team productivity."),
            )
        conn.execute(
            "INSERT INTO messages (id, thread_id, direction, role, content, status) "
            "VALUES (10, 1, 'outbound', 'opener', "
            "'Keith, noticed logistics teams are stretched thin lately. How are you coping?', 'draft')"
        )
        conn.execute(
            "INSERT INTO messages (id, thread_id, direction, role, content, status) "
            "VALUES (11, 2, 'outbound', 'opener', "
            "'Xia Dan, marketing output demands keep climbing. What is your team leaning on?', 'draft')"
        )
        conn.execute(
            "INSERT INTO messages (id, thread_id, direction, role, content, status) "
            "VALUES (12, 3, 'outbound', 'opener', 'Adibah, HR consultancies...', 'skipped')"
        )
        conn.commit()
    finally:
        conn.close()


def install_spies() -> None:
    """Record every tool call; stub the slow/external ones."""
    real = dict(brain.TOOL_IMPLS)

    def spy(name):
        def wrapper(args, ctx):
            CALLS.append((name, dict(args)))
            return real[name](args, ctx)
        return wrapper

    def stubbed(name, result_fn):
        def wrapper(args, ctx):
            CALLS.append((name, dict(args)))
            return result_fn(args)
        return wrapper

    for tool in brain.TOOL_IMPLS:
        brain.TOOL_IMPLS[tool] = spy(tool)

    def stub_redraft(args):
        row, err = brain._resolve_draft(args.get("name", ""))
        if err:
            return err
        return (
            f"New draft for {row['name']} (142 chars) — show it to Zico:\n"
            f"[stub rewrite applying: {args.get('instruction', '')}]"
        )

    brain.TOOL_IMPLS["redraft"] = stubbed("redraft", stub_redraft)
    brain.TOOL_IMPLS["redraft_all"] = stubbed(
        "redraft_all", lambda a: "All drafts rewritten (stub)."
    )
    brain.TOOL_IMPLS["start_prospecting"] = stubbed(
        "start_prospecting",
        lambda a: "Prospecting started in the background (stub).",
    )
    brain.TOOL_IMPLS["book_meeting"] = stubbed(
        "book_meeting",
        lambda a: f"Booked: {a.get('prospect_name')} on {a.get('date')} "
                  f"{a.get('time')} at {a.get('location')} (stub).",
    )
    brain.TOOL_IMPLS["health_check"] = stubbed(
        "health_check", lambda a: "All systems OK (stub)."
    )


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {label}")
    else:
        FAIL += 1
        print(f"FAIL  {label}  {detail}")


def called(tool: str) -> list[dict]:
    return [args for name, args in CALLS if name == tool]


def scenario(title: str, *turns: str) -> list[str]:
    """Run a multi-turn scenario in a fresh conversation; return bot replies."""
    print(f"\n=== {title}")
    reset_data()
    CALLS.clear()
    brain.reset_history(CHAT_ID)
    replies = []
    for turn in turns:
        print(f"  Zico: {turn}")
        result = brain.handle_message(CHAT_ID, turn)
        reply = result["reply"]
        replies.append(reply)
        shown = reply.replace("\n", " | ")[:160]
        print(f"  Bot:  {shown}")
    return replies


def main() -> int:
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY missing in .env — cannot run the live eval.")
        return 2

    seed_db()
    install_spies()

    # 1. The original complaint: a tone request must become a redraft.
    scenario(
        "tone adjustment, single target named",
        "make keith's draft more casual",
    )
    redrafts = called("redraft")
    check(
        "tone request -> redraft tool, keith, casual",
        any("keith" in a.get("name", "").lower() and a.get("instruction") for a in redrafts),
        f"calls={CALLS}",
    )
    check("did not misroute to edit_draft", not called("edit_draft"), f"calls={CALLS}")

    # 2. Ambiguous tone request, then a follow-up answer — tests MEMORY.
    replies = scenario(
        "ambiguous tone request resolved by follow-up",
        "adjust the tone a bit",
        "the keith one — more casual please",
    )
    redrafts = called("redraft")
    check(
        "follow-up answer understood (redraft keith)",
        any("keith" in a.get("name", "").lower() for a in redrafts),
        f"calls={CALLS}",
    )

    # 3. Send must stage a confirmation, never bypass.
    scenario("send request", "send keith")
    check("send -> prepare_send", len(called("prepare_send")) >= 1, f"calls={CALLS}")

    # 4. Compound command — two actions in one message.
    scenario("compound command", "skip xia dan and send keith")
    check(
        "compound: skip xia dan",
        any("xia" in a.get("name", "").lower() or "dan" in a.get("name", "").lower()
            for a in called("skip_draft")),
        f"calls={CALLS}",
    )
    check("compound: prepare_send keith", len(called("prepare_send")) >= 1, f"calls={CALLS}")

    # 5. Research question.
    scenario("research question", "who is xia dan?")
    check("research -> get_research", len(called("get_research")) >= 1, f"calls={CALLS}")

    # 6. Prospecting in natural words.
    scenario("prospecting", "find me 2 new leads from the bni list")
    pros = called("start_prospecting")
    check("prospecting triggered", len(pros) >= 1, f"calls={CALLS}")

    # 7. Booking with a relative date.
    scenario("booking", "booked keith tomorrow 2pm at bangsar")
    books = called("book_meeting")
    check(
        "booking parsed (keith, 14:00, bangsar)",
        any(
            "keith" in a.get("prospect_name", "").lower()
            and a.get("time") == "14:00"
            and "bangsar" in a.get("location", "").lower()
            for a in books
        ),
        f"calls={CALLS}",
    )

    # 8. Health check in plain words.
    scenario("health", "is everything ok?")
    check("health check triggered", len(called("health_check")) >= 1, f"calls={CALLS}")

    # 9. Restore a skipped draft.
    scenario("restore", "actually bring adibah back")
    check("restore_draft adibah", len(called("restore_draft")) >= 1, f"calls={CALLS}")

    # 10. Bare 'yes' after the bot itself asked about sending — memory again.
    scenario(
        "confirmation follow-up",
        "I think keith's draft is ready",
        "yes send it",
    )
    check(
        "eventual prepare_send for keith",
        len(called("prepare_send")) >= 1,
        f"calls={CALLS}",
    )

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
