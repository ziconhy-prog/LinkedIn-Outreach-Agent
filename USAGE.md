# LinkedIn Outreach Agent — How to Use

This is your day-to-day guide for operating the system. Everything you need to
do happens through Telegram. The Mac just needs to be running with the bot
process alive.

---

## 1. Daily Workflow (the 5-minute morning routine)

A typical day looks like this — all from Telegram on your phone:

1. **Check the queue.** Say `"show queue"` → bot shows pending drafts.
2. **Triage drafts.** For each one, either:
   - `"send Keith"` → fires the connection-with-note flow
   - `"skip Adibah, find someone else"` → drops it + pulls a replacement
   - `"edit Keith to say: [new text]"` → manual edit
   - `"redraft Keith — lead with the founder operations angle"` → AI regenerates
   - `"tell me about Adibah"` → shows BNI data + research brief before deciding
3. **Pull more prospects.** `"find new prospects"` → bot pulls fresh BNI candidates,
   searches LinkedIn, scrapes profiles, drafts openers (~2 min per prospect).
4. **Walk away.** Inbox poller runs Mon-Fri at 10am / 12pm / 4pm. Daily summary
   pings you at 5pm.

That's it. No need to touch the Mac unless something breaks.

---

## 2. Talking to the Bot (natural language only)

The bot uses Claude Haiku to understand intent. Slash commands are gone — just
type naturally. Examples:

| What you want | What to say |
|---|---|
| See pending drafts | "show queue" / "what's pending" / "show me the drafts" |
| Send a draft | "send Keith" / "approve Adibah" / "send it" (after queue shown) |
| Skip a draft | "skip Bernard" / "delete KC Lim" / "scrap that one" |
| Skip + replace | "skip Bernard, find a new one" |
| Edit a draft | "edit Keith to say: Hey Keith, just curious..." |
| AI redraft with new angle | "redraft Adibah — try the founder operations angle" |
| Restore a skipped draft | "bring back Keith" / "actually keep that one" |
| Profile + brief on a prospect | "tell me about Keith" / "who is Adibah" |
| Start a prospecting run | "find new prospects" / "scrape the BNI list" |
| Book a meeting | "booked Keith 25 May 2pm Bangsar" |
| System status | "status" / "how's it going" |

For sending, the bot **only** accepts explicit verbs (`send`, `approve`, `ship`,
`fire`, `dispatch`). Bare confirmations like "yes" or "ok" are safe — they ask
you to be specific instead of firing anything.

---

## 3. What Happens Automatically (no approval needed)

- **Inbox polling** (Mon-Fri, 10am/12pm/4pm) — scans LinkedIn for new replies
- **Reply drafting** — when a prospect replies normally, the bot drafts a
  response and sends it after a 15-45 min humanlike delay
- **Meeting booking flow** — when a prospect agrees to meet, the bot asks for
  a location, waits for their answer, and books the calendar event
- **Daily 5pm report** — Telegram message summarizing new accepts, replies,
  meetings booked, and any escalations

---

## 4. What Flags to You (you must handle manually)

The bot pings you with `⚠️ NEEDS YOU — [reason]` when:

- **Pricing question** — prospect asks about cost
- **Aggressive reply** — angry or hostile message
- **Not interested** — explicit rejection
- **Meeting request** — they propose a specific time/place
- **Architecture / tech question** — they ask about how SkillTrainer works internally
- **Uncertain** — bot doesn't know how to handle it (partnerships, hiring,
  off-topic, anything outside SkillTrainer/AI training)

When this fires, **no auto-reply is sent**. Run `"show queue"` to see the
flagged message and decide manually.

---

## 5. The Send Flow (what actually happens when you say "send Keith")

1. Bot opens a **visible** browser window
2. Navigates to Keith's LinkedIn profile
3. Clicks **More → Connect → Add a note**
4. Types the draft into the note (300-char limit enforced)
5. Clicks **Send invitation**
6. Marks the message `sent` in the DB and confirms back to Telegram

If anything fails (LinkedIn UI quirk, captcha, already connected), the draft is
**restored to the queue** and you get a clear error. Debug screenshots auto-save
to `logs/send_failures/`.

---

## 6. Voice Tuning (when drafts feel off)

The drafter follows 5 strict voice rules saved to memory:

1. **Don't educate** the prospect — no "this is common when…" generalizations
2. **Prospects ARE the seniors** — never "senior people / execs / leadership"
3. **Don't undermine** their inputs — no "well actually" or reinterpreting
4. **You ARE Zico** — first person only, never reveal automation
5. **Escalate cleanly** — output only `ESCALATE:uncertain` when unsure

If a draft slips on any of these in real conversations, just tell me in chat
(e.g. "stop sounding consultanty"). I'll tighten the prompt and save the new
rule to memory.

---

## 7. Daily Limits (LinkedIn safety)

| Action | Daily cap |
|---|---|
| Profile views | 80 |
| Name searches | unlimited (no hard cap) |
| Connection requests | **15** ← the main constraint |
| Messages sent (post-connect) | 25 |

The system enforces these automatically — sends are blocked if you'd exceed.
A realistic batch is 8-12 connect-with-notes per day, leaving safety margin.

---

## 8. Running the Bot

**Start:**
```bash
cd "/Users/zicong/Desktop/LinkedIn Outreach Agent"
python -m outreach telegram-poll &
```

**Check it's running:**
```bash
ps aux | grep "outreach telegram-poll" | grep -v grep
```

**Stop:**
```bash
kill <PID>
```

**Restart (after any code change):**
```bash
kill <old PID> && python -m outreach telegram-poll &
```

The inbox poller and daily report run via launchd plists in `~/Library/LaunchAgents/`.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot stops responding | Process died or Haiku overloaded | Check `ps aux`, restart |
| "LinkedIn session expired" | Cookie/session timeout | Run `python -m outreach linkedin-login` |
| Send fails with "compose box not found" | Prospect isn't 1st-degree (need Premium connect flow — should be fixed now) | Check `logs/send_failures/` for screenshot |
| Draft too long for connect note | Over 300 chars | Bot rejects automatically; redraft with shorter instruction |
| Same prospect re-appearing in prospecting | `enrichment_status` stuck on 'pending' | DB: `UPDATE prospects SET enrichment_status='not_found' WHERE name LIKE '%xxx%'` |
| Bot replies feel off | Voice rule slipping | Tell me in chat — I'll tighten the rule and save to memory |

---

## 10. Cost Per Action (current, Sonnet 4.6)

| Action | Cost |
|---|---|
| Telegram message routing | ~$0.002 |
| One AI redraft (warm cache) | ~$0.015-0.04 |
| Full prospect pipeline (brief + opener) | ~$0.07 |
| One inbox auto-reply | ~$0.025 |
| Sending a connection invite (browser only) | $0 |

Typical monthly bill at ~100 prospects + iteration: **~$15-25**.

---

## 11. The Hard Rules (will never be bypassed)

- Bot will never send to LinkedIn without the message being in the DB as
  `approved` or `auto_draft` status
- Bot will never send a connection note over 300 chars
- Bot will never message the same prospect twice in the same day
- Bot will never auto-reply to escalated messages (pricing, meeting, aggressive,
  uncertain, architecture)
- Bot will never identify itself as automated or refer to "Zico" in third person
- The `ESCALATE:uncertain` token is intercepted before any LinkedIn send — the
  prospect never sees it; only you get the Telegram alert

---

When something breaks or feels off, just tell me in chat. The whole point is
that this gets better over time without you having to touch code.
