"""Offline tests — no API key, no browser, no network.

Run:  python tests/test_offline.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Point the app at a throwaway DB BEFORE importing outreach.config.
_TMP = tempfile.mkdtemp(prefix="outreach_test_")
os.environ["DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("ANTHROPIC_API_KEY", "")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok  {label}")
    else:
        FAIL += 1
        print(f"FAIL  {label}  {detail}")


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def test_classifier() -> None:
    from outreach.classifier import classify

    print("\nclassifier:")
    cases = [
        # (message, expected)
        ("Thanks for reaching out! What does your company do?", "normal"),
        ("How much does it cost per user?", "pricing"),
        ("Not interested, thanks", "not_interested"),
        ("Stop messaging me or I'll report you", "aggressive"),
        ("Sure, let's meet for coffee sometime", "meeting_request"),
        ("Sounds good, see you Friday afternoon", "meeting_confirmed"),
        # Former false positives — generic tech words in normal chat:
        ("I integrated the API recently for my shop's billing", "normal"),
        ("Security guards are a big cost for our mall business", "normal"),
        ("We use an LMS already but staff hate it", "normal"),
        # Former false positive — enthusiasm + month name is NOT a confirmed meeting:
        ("Perfect timing, we're hiring in May", "normal"),
        ("Looking forward to your reply tomorrow", "normal"),
        # Real architecture questions still escalate:
        ("What's your tech stack? Is it built on GPT?", "architecture_question"),
        ("How does it work technically with our data privacy?", "architecture_question"),
        # Strong confirmations still detected:
        ("Works for me, Tuesday 3pm then", "meeting_confirmed"),
        ("Let's do Thursday morning", "meeting_confirmed"),
    ]
    for text, expected in cases:
        got = classify(text)
        check(f"classify({text[:45]!r}) == {expected}", got == expected, f"got {got}")


# ---------------------------------------------------------------------------
# Drafter conversation stage
# ---------------------------------------------------------------------------

def test_conversation_stage() -> None:
    from outreach.drafter import _conversation_stage, _STAGE_INSTRUCTIONS

    print("\nconversation stage:")
    # Opener sent (outbound_count=1) -> first reply must be stage 2, NOT stage 4.
    check("outbound_count=1 -> stage 2", _conversation_stage(1) == 2)
    check("outbound_count=2 -> stage 3", _conversation_stage(2) == 3)
    check("outbound_count=3 -> stage 4", _conversation_stage(3) == 4)
    check("outbound_count=9 -> stage 4 (cap)", _conversation_stage(9) == 4)
    # Defensive lower clamp: never below stage 2.
    check("outbound_count=0 -> stage 2 (clamp)", _conversation_stage(0) == 2)
    # Every reachable stage has instructions (no silent fall-through to 4).
    for n in range(0, 6):
        s = _conversation_stage(n)
        check(f"stage {s} has instructions", s in _STAGE_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# Brain draft resolution + history trimming (DB-backed, no API)
# ---------------------------------------------------------------------------

def _seed_db() -> None:
    from outreach.config import PROJECT_ROOT
    from outreach.db.connection import get_connection

    schema = (PROJECT_ROOT / "outreach" / "db" / "schema.sql").read_text(encoding="utf-8")
    conn = get_connection()
    try:
        conn.executescript(schema)
        for pid, name in [(1, "Keith Ngai"), (2, "Xia Dan Duar"), (3, "Adibah Noor")]:
            conn.execute(
                "INSERT INTO prospects (id, name, company, source, source_id) "
                "VALUES (?, ?, ?, 'test', ?)",
                (pid, name, f"Company {pid}", f"test-{pid}"),
            )
            conn.execute(
                "INSERT INTO threads (id, prospect_id, status) VALUES (?, ?, 'queued')",
                (pid, pid),
            )
        conn.execute(
            "INSERT INTO messages (id, thread_id, direction, role, content, status) "
            "VALUES (10, 1, 'outbound', 'opener', 'draft for keith', 'draft')"
        )
        conn.execute(
            "INSERT INTO messages (id, thread_id, direction, role, content, status) "
            "VALUES (11, 2, 'outbound', 'opener', 'draft for xia dan', 'draft')"
        )
        conn.execute(
            "INSERT INTO messages (id, thread_id, direction, role, content, status) "
            "VALUES (12, 3, 'outbound', 'opener', 'skipped for adibah', 'skipped')"
        )
        conn.commit()
    finally:
        conn.close()

    from outreach.db import migrations

    migrations.run()  # adds send_after & friends on top of the base schema


def test_brain_resolution() -> None:
    from outreach import telegram_brain as brain

    print("\nbrain draft resolution:")
    row, err = brain._resolve_draft("keith")
    check("'keith' resolves", err is None and row and row["id"] == 10, f"err={err}")
    row, err = brain._resolve_draft("KEITH NGAI")
    check("full name, any case", err is None and row and row["id"] == 10, f"err={err}")
    row, err = brain._resolve_draft("dan")
    check("'dan' -> Xia Dan via token match", err is None and row and row["id"] == 11, f"err={err}")
    row, err = brain._resolve_draft("bernard")
    check("unknown name -> error listing queue", row is None and "Keith Ngai" in (err or ""), f"err={err}")
    row, err = brain._resolve_draft("")
    check("empty name + 2 drafts -> ask which", row is None and "Which one" in (err or ""), f"err={err}")
    row, err = brain._resolve_draft("adibah", statuses=("skipped",))
    check("skipped lookup finds Adibah", err is None and row and row["id"] == 12, f"err={err}")

    # Tool wrappers return readable strings.
    out = brain._tool_get_queue()
    check("get_queue lists both drafts", "Keith Ngai" in out and "Xia Dan Duar" in out)
    out = brain._tool_get_skipped()
    check("get_skipped lists Adibah", "Adibah" in out)
    out = brain._tool_skip_draft("keith")
    check("skip_draft works", "Skipped" in out and "Keith" in out)
    out = brain._tool_restore_draft("keith")
    check("restore_draft brings it back", "Restored" in out and "Keith" in out)
    out = brain._tool_edit_draft("keith", "x" * 350)
    check("edit_draft rejects >300 chars", "300" in out)
    out = brain._tool_edit_draft("keith", "Hey Keith, short and sweet.")
    check("edit_draft saves valid text", "Updated" in out)


def test_brain_history_trim() -> None:
    from outreach import telegram_brain as brain

    print("\nbrain history trimming:")
    msgs = []
    for i in range(30):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": f"a{i}"}]})
    trimmed = brain._trim_history(msgs)
    check("history capped", len(trimmed) <= brain._MAX_HISTORY_MESSAGES)
    check(
        "history starts with plain user text",
        trimmed[0]["role"] == "user" and isinstance(trimmed[0]["content"], str),
    )
    # Must never start on a tool_result block (API would reject it).
    msgs2 = [
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "y"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a"}]},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "b"}]},
    ]
    trimmed2 = brain._trim_history(msgs2)
    check(
        "tool_result head dropped",
        trimmed2 and trimmed2[0]["content"] == "hello",
    )


# ---------------------------------------------------------------------------
# Inbox scheduling math
# ---------------------------------------------------------------------------

def test_send_after_scheduling() -> None:
    from datetime import datetime, timezone

    from outreach import inbox_handler as ih

    print("\ninbox scheduling:")
    # _store_auto_draft stamps a future send_after.
    from outreach.db.connection import get_connection

    draft_id = ih._store_auto_draft(1, "scheduled reply", delay_s=600)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT send_after, status FROM messages WHERE id = ?", (draft_id,)
        ).fetchone()
    finally:
        conn.close()
    check("auto_draft stored", row["status"] == "auto_draft")
    send_after = datetime.fromisoformat(row["send_after"])
    delta = (send_after - datetime.now(timezone.utc)).total_seconds()
    check("send_after ~10min out", 540 < delta < 660, f"delta={delta}")

    # Lock: second acquire fails, release frees it.
    check("lock acquired", ih._acquire_lock())
    check("second acquire blocked", not ih._acquire_lock())
    ih._release_lock()
    check("lock released and reacquirable", ih._acquire_lock())
    ih._release_lock()


def main() -> int:
    test_classifier()
    test_conversation_stage()
    _seed_db()
    test_brain_resolution()
    test_brain_history_trim()
    test_send_after_scheduling()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
