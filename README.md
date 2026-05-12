# LinkedIn Outreach Agent

Personal LinkedIn outreach automation for SkillTrainer AI. Drafts personalized
messages, manages reply conversations, and books meetings — with you approving
every send via Telegram.

## What this does (in plain English)

Each workday at 10am Malaysia time, the system pulls 10 prospects from your
BNI Malaysia member list (plus a few from hashtag-driven LinkedIn searches),
researches each one quietly, and prepares opener drafts. You approve each
message in Telegram with a tap. When prospects reply, the system drafts
replies the same way. When someone agrees to meet and proposes a time, the
bot blocks the slot on your Google Calendar.

You never type code. You touch Telegram and (one time) double-click a setup
file. Everything else runs locally on your Mac.

## One-time setup

1. Open Finder, find this folder.
2. Double-click **`setup.command`**.
3. macOS may ask "Are you sure you want to open this?" — click **Open**.
4. Wait ~2 minutes while it installs. Press any key when it's done.

That's it for now. Later phases (Telegram bot, LinkedIn login, Google
Calendar) will guide you through one extra step each when their turn comes.

## What's working in v1 (right now)

- Local database is initialized
- BNI member list can be parsed from PDF
- Voice samples (your 20 reference messages) can be loaded
- Dry-run batches can be generated from the local prospect list without
  sending anything

## Running a dry-run batch

This only suggests candidates from the local database. It does **not** send
LinkedIn messages and does **not** mean the LinkedIn profile is already
validated.

```bash
./.venv/bin/python -m outreach dry-run-batch --limit 5 --markdown
```

For each suggested candidate, the next step is still:

1. Search LinkedIn by name only.
2. Validate company, headline, and Malaysia/SEA location from the result list.
3. Open the matched profile and research recent posts/engagement if available.
4. Only say "saw your post" if that post was actually captured.
5. Draft the opener for review. Do not send.

## Connecting Telegram

Telegram is the approval cockpit. Later, every draft will wait there for your
tap before anything is sent.

1. In Telegram, talk to `@BotFather`.
2. Create a bot and copy the token into `.env` as `TELEGRAM_BOT_TOKEN`.
3. Talk to `@userinfobot` and copy your numeric ID into `.env` as
   `TELEGRAM_OPERATOR_USER_ID`.
4. Check the connection:

```bash
./.venv/bin/python -m outreach telegram-status
```

5. Send yourself a harmless test message:

```bash
./.venv/bin/python -m outreach telegram-test
```

These commands do not touch LinkedIn.

## What's coming next

| Phase | What it adds |
|---|---|
| 2 | LinkedIn search + profile reading via Playwright |
| 3 | Opener drafting in your voice (uses voice-samples/) |
| 4 | Telegram cockpit — you start approving drafts here |
| 5 | Live LinkedIn sending (after a dry-run review) |
| 6 | Auto reply handling with humanlike delays |
| 7 | Stop rules + 1-day-gap follow-ups |
| 8 | Google Calendar booking |
| 9 | Daily 5pm report |

## If something breaks

- Logs are in `logs/` — open the most recent file in TextEdit and send a
  screenshot of any error.
- The database is at `data/outreach.db` — leave it alone unless asked.
- If `setup.command` fails, take a screenshot of the Terminal output.

## Project structure

- `files/` — PRD, CLAUDE.md, voice samples, setup notes
- `outreach/` — the Python code (don't edit by hand)
- `data/` — your local database (don't share or copy off this Mac)
- `logs/` — runtime logs

The `data/` folder is encrypted at rest by your Mac's FileVault. Don't copy
the database file to an unencrypted drive or to cloud storage.

## Privacy notes

Prospect data on LinkedIn is third-party personal data under PDPA (Malaysia,
Singapore) and GDPR (anyone EU-based). The system is designed to keep all of
it local: no cloud CRMs, no third-party analytics, no shared servers. The
only outbound traffic from your Mac is to LinkedIn (via your logged-in
session), Telegram (your bot, your account), and — once Phase 8 lands —
Google Calendar (your account). That's it.

If a prospect ever asks to be removed, we have a do-not-contact list that
permanently blocks them and deletes their research data.
