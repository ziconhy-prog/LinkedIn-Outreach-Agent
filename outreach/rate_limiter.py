"""Daily rate limits at the tool layer.

Per CLAUDE.md: hard caps sit *below* LinkedIn's known soft thresholds.
Each name search counts as 2 against the profile-view budget (the search
results page itself plus the click-through). Connect requests and message
sends each have their own daily cap.

Counts are derived from audit_log rows in the current calendar day
(operator's local timezone — Malaysia by default).
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from outreach.db.connection import get_connection


# Per-action cost (how much of a budget one action consumes)
ACTION_COST: dict[str, int] = {
    "profile_view": 1,
    "name_search": 2,
    "connection_request": 1,
    "message_send": 1,
}

# Daily caps per budget. Profile views and name searches share one budget.
DAILY_CAP: dict[str, int] = {
    "profile_view_budget": 80,
    "connection_request_budget": 15,
    "message_send_budget": 25,
}

# Which actions consume which budget
ACTION_TO_BUDGET: dict[str, str] = {
    "profile_view": "profile_view_budget",
    "name_search": "profile_view_budget",
    "connection_request": "connection_request_budget",
    "message_send": "message_send_budget",
}

# Reverse map: budget -> actions that consume it
BUDGET_TO_ACTIONS: dict[str, list[str]] = {}
for _action, _budget in ACTION_TO_BUDGET.items():
    BUDGET_TO_ACTIONS.setdefault(_budget, []).append(_action)


class RateLimitExceeded(Exception):
    """Raised when an action would exceed its daily cap."""


def used_today(budget_name: str, conn: Optional[sqlite3.Connection] = None) -> int:
    """Return how much of ``budget_name`` has been consumed today."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    assert conn is not None
    try:
        actions = BUDGET_TO_ACTIONS.get(budget_name, [])
        if not actions:
            return 0
        placeholders = ",".join("?" * len(actions))
        # Count successful actions only — failed attempts don't count.
        rows = conn.execute(
            f"""
            SELECT action, COUNT(*) AS n
            FROM audit_log
            WHERE success = 1
              AND action IN ({placeholders})
              AND DATE(timestamp, 'localtime') = DATE('now', 'localtime')
            GROUP BY action
            """,
            actions,
        ).fetchall()
        used = 0
        for row in rows:
            used += ACTION_COST.get(row["action"], 1) * row["n"]
        return used
    finally:
        if own_conn:
            conn.close()


def can_perform(action: str, conn: Optional[sqlite3.Connection] = None) -> bool:
    """Return True if ``action`` is within today's budget."""
    if action not in ACTION_TO_BUDGET:
        # Unknown actions are allowed (logged but not budgeted).
        return True
    budget = ACTION_TO_BUDGET[action]
    cap = DAILY_CAP[budget]
    cost = ACTION_COST[action]
    return used_today(budget, conn) + cost <= cap


def check(action: str, conn: Optional[sqlite3.Connection] = None) -> None:
    """Raise RateLimitExceeded if ``action`` would breach today's cap."""
    if not can_perform(action, conn):
        budget = ACTION_TO_BUDGET[action]
        cap = DAILY_CAP[budget]
        used = used_today(budget, conn)
        raise RateLimitExceeded(
            f"Daily cap reached for {budget}: {used}/{cap}. "
            f"Cannot perform {action!r} until tomorrow (Malaysia time)."
        )


def status(conn: Optional[sqlite3.Connection] = None) -> dict[str, dict[str, int]]:
    """Return today's budget usage as a flat dict for reporting."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()
    assert conn is not None
    try:
        out: dict[str, dict[str, int]] = {}
        for budget, cap in DAILY_CAP.items():
            out[budget] = {"used": used_today(budget, conn), "cap": cap}
        return out
    finally:
        if own_conn:
            conn.close()
