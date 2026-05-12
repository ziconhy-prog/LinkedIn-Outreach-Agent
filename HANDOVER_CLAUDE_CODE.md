# Claude Code Handover: LinkedIn Outreach Agent

Last inspected: 2026-05-11, Asia/Kuala_Lumpur  
Workspace: `/Users/zicong/Desktop/SkillTrainer AI/LinkedIn Outreach Agent`  
Current git branch: `main`  
Last committed revision: `7a23748 docs: add PRD, CLAUDE.md, and setup guide for v1`

This project is mid-build and has many untracked files. Do not assume git only
contains the full project. Inspect the working tree before changing anything.

## 1. Project Purpose And Automation Workflow

This is a local-first LinkedIn cold outreach assistant for SkillTrainer AI.
Its purpose is to help Zico find suitable Malaysia/SEA prospects, research
their LinkedIn profile/activity, draft human-sounding messages in Zico's voice,
and eventually manage reply conversations toward face-to-face meetings.

Critical positioning: this is **drafting and approval infrastructure**, not an
autonomous sender. The system must never send LinkedIn messages, connection
requests, reactions, replies, or calendar confirmations unless Zico explicitly
approves through Telegram.

Target prospects:

- Primary source: BNI Malaysia member list stored in `data/BNI_Malaysia_Potential_Clients.xlsx - All Candidates.pdf`.
- Priority categories: marketing/creative agencies, HR consultancies, training companies, professional services, retail/service SMEs, conventional non-AI SMEs.
- Avoid: AI-provider companies, AI automation agencies, chatbot vendors, AI training providers, direct competitors, unclear LinkedIn matches, and profiles outside Malaysia/SEA unless clearly tied to the target geography.

Intended workflow:

1. Local database stores BNI prospects.
2. Dry-run or daily surfacing suggests candidate prospects.
3. LinkedIn is searched **by name only**.
4. Search result list is inspected for company, headline, and Malaysia/SEA location.
5. Uncertain matches are rejected.
6. For valid matches, Playwright opens the profile and captures visible profile data and recent posts/activity.
7. Claude Code uses `prompts/research_brief.md` to synthesize a research brief.
8. Claude Code uses `prompts/opener.md` plus voice samples from `files/voice-samples/` to draft an opener.
9. Draft is saved locally as a `messages.status='draft'` row.
10. Future Telegram approval queue shows draft to Zico with Approve/Edit/Skip/Defer.
11. Only after Telegram approval should any LinkedIn send path execute.
12. Reply handling, follow-ups, stop rules, Google Calendar booking, and daily reports are future phases.

Important tone strategy:

- Opener should be hook-led and relaxed, not formal or robotic.
- Prefer a recent post/comment/repost/engagement hook only when Playwright actually captured it.
- Hard rule: never say "saw your post", "noticed your post", "your recent post", or reference a comment/repost unless that exact activity is in captured research data.
- If no useful activity exists, use profile/company/category context or a market-truth hook.
- Do not mention BNI or source list.
- Do not mention or pitch SkillTrainer AI in the opener.
- Introduce SkillTrainer AI only after the conversation surfaces relevant pain around team productivity, training gaps, AI adoption, execution inconsistency, or workflow friction.

## 2. Current Implementation Status

Working locally:

- Python package `outreach` exists and compiles.
- Virtualenv exists at `.venv/`.
- Setup script exists at `setup.command`.
- SQLite database exists at `data/outreach.db`.
- BNI list has been parsed into 725 prospects.
- Voice samples load successfully: 20 `.rtf` files in `files/voice-samples/`.
- Basic CLI exists with commands for setup, LinkedIn login/status/search/profile, research prompt generation, opener prompt generation, saving briefs/openers, Telegram status/test, and dry-run batch generation.
- Telegram token and operator user ID are present in `.env` on this machine. Do not print or commit them.
- Telegram bot token previously validated successfully as `@STAI_LinkedIn_Bot`; final delivery test was blocked by the previous Codex session's tool/network limit after the user pressed Start.
- Playwright session directory exists at `.playwright-session/`, created during earlier LinkedIn login work.
- One enriched/researched prospect exists in DB: prospect id `34`, Deni Temirov, LinkedIn URL `https://www.linkedin.com/in/temirovd`.
- One research row, one brief, one thread, and one draft message exist in DB.
- Dry-run batch command works and prints pre-validation candidates.

Not implemented yet:

- Real Telegram approval queue with inline buttons.
- Operator ID authorization on inbound bot updates.
- Telegram polling or webhook loop.
- LinkedIn send path.
- Queue-entry-only send enforcement.
- Inbox polling and reply handling.
- Humanlike reply delays.
- Follow-up stop rules.
- Google Calendar OAuth and booking.
- Daily 10am surfacing job.
- Daily 5pm report.
- Hashtag-based LinkedIn discovery.
- Proper test suite.
- Lint/format config.

## 3. File And Folder Structure

Root files:

- `README.md`: user-facing overview, setup, dry-run command, Telegram setup instructions. Recently updated.
- `HANDOVER_CLAUDE_CODE.md`: this handover file.
- `requirements.txt`: Python dependencies.
- `setup.command`: double-clickable macOS setup script. Creates `.venv`, installs dependencies, installs Playwright Chromium, copies `.env.example` to `.env`, initializes DB.
- `.env.example`: env var template. Safe to commit.
- `.env`: real local secrets file. Ignored by git. Do not print, copy, or commit.
- `.gitignore`: ignores `.env`, `.venv`, local DB/data/logs, `.playwright-session`, `.playwright-mcp`, editor files.
- `.mcp.json`: Claude/VS Code MCP config for Playwright MCP via `npx @playwright/mcp@latest`.
- `.claude/settings.local.json`: local Claude settings currently allowing `mcp__playwright__browser_snapshot`.
- `.codex/config.toml`: old Codex MCP config. Not important for Claude Code but useful historical context.

Docs and requirements:

- `files/PRD.md`: detailed product requirements. Updated heavily from original. Contains target users, workflow, Telegram approval model, LinkedIn safety, privacy, out-of-scope, open questions.
- `files/CLAUDE.md`: main agent instructions. Claude Code should read this first after PRD. Contains non-negotiable rules, voice rules, prospect-fit validation, tone rules, privacy, phase status, and implementation constraints.
- `files/SETUP.md`: older setup guide and context. Some content may be stale compared to `README.md`, `PRD.md`, and `CLAUDE.md`.
- `files/voice-samples/*.rtf`: 20 voice samples. `outreach.ingest.voice_samples` parses these with `striprtf`.

Prompt files:

- `prompts/research_brief.md`: prompt template for turning raw prospect/profile data into a structured research brief. Includes hard evidence rule for post/engagement hooks.
- `prompts/opener.md`: prompt template for drafting the opener. Includes voice rules, hook ladder, hard evidence rule, no-BNI/no-product opener rule, and conversation progression.

Python package:

- `outreach/__init__.py`: package version `0.1.0`.
- `outreach/__main__.py`: CLI entry point. Most commands live here.
- `outreach/config.py`: loads `.env`, resolves paths, exposes `DATA_DIR`, `LOGS_DIR`, `DB_PATH`, `VOICE_SAMPLES_DIR`, `PLAYWRIGHT_USER_DATA_DIR`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OPERATOR_USER_ID`.
- `outreach/db/schema.sql`: SQLite schema for prospects, threads, messages, audit_log, do_not_contact, daily_reports, research.
- `outreach/db/connection.py`: opens SQLite connection to `DB_PATH` with `row_factory=sqlite3.Row`.
- `outreach/ingest/bni_parser.py`: parses BNI PDF with `pdfplumber`, inserts prospects.
- `outreach/ingest/voice_samples.py`: loads `.rtf` voice samples via `striprtf`.
- `outreach/playwright_client.py`: Python Playwright persistent Chromium session manager using `.playwright-session`.
- `outreach/linkedin/session.py`: interactive login and headless session check.
- `outreach/linkedin/search.py`: searches LinkedIn people by name only, returns first `/in/` URL. This is currently too naive; see bugs.
- `outreach/linkedin/profile.py`: reads profile page title/headline/location and recent activity page posts.
- `outreach/research.py`: gathers profile/posts into `research.raw_json`, retrieves/saves briefs, enriches prospect with LinkedIn URL.
- `outreach/drafting.py`: saves opener draft into thread/messages tables.
- `outreach/rate_limiter.py`: daily budget checks based on `audit_log`.
- `outreach/audit.py`: appends audit rows.
- `outreach/telegram_client.py`: minimal Telegram Bot API helper for `getMe` and test `sendMessage`, using `certifi` SSL context.

Local data:

- `data/outreach.db`: local SQLite DB. Ignored by git.
- `data/BNI_Malaysia_Potential_Clients.xlsx - All Candidates.pdf`: source BNI PDF. Ignored by git.
- `data/brief_34.md`, `data/opener_34.txt`: historical brief/opener artifacts for prospect 34.
- `data/dry_run_2026-05-08*.md`: dry-run notes and simulations from tone/prospect testing. Ignored by git.
- `data/prospecting_rules_2026-05-08.md`: local summary of prospecting rules. Ignored by git.

Runtime/session data:

- `.playwright-session/`: persistent Chromium profile for LinkedIn. Treat as credential.
- `.playwright-mcp/`: Playwright MCP runtime artifacts. Ignored.
- `logs/`: currently empty.

## 4. Tech Stack, Dependencies, APIs, MCP/Tools, External Services

Language/runtime:

- Python 3.11+ required by `setup.command`. Current venv path: `.venv/`.
- Current local venv appears to be Python 3.14 based on `.venv/lib/python3.14`.

Python dependencies in `requirements.txt`:

- `pdfplumber>=0.11.0`: parse BNI PDF tables.
- `striprtf>=0.0.26`: parse RTF voice samples.
- `python-dotenv>=1.0.1`: load `.env`.
- `certifi>=2024.8.30`: TLS certificate bundle for Telegram API calls.
- `playwright>=1.49.0`: Python browser automation.
- `tf-playwright-stealth>=1.1.0`: installed but not currently imported anywhere.

External services:

- LinkedIn: read/search/profile automation via Playwright. Must be local, modest volume, human-approved for any send.
- Telegram Bot API: intended approval cockpit. Currently only status/test helper is implemented.
- Google Calendar: planned only. No code yet.
- Claude Code / Claude Pro: LLM drafting is interactive through Claude Code only. No Anthropic API, no API keys, no background LLM calls in v1.

MCP/tools:

- `.mcp.json` configures Playwright MCP:
  ```json
  {
    "mcpServers": {
      "playwright": {
        "type": "stdio",
        "command": "npx",
        "args": ["@playwright/mcp@latest"],
        "env": {}
      }
    }
  }
  ```
- Python code uses its own Playwright session via `outreach/playwright_client.py`; this is separate from MCP. MCP is useful for Claude Code exploration/debugging.

## 5. Completed Work

Completed and verified:

- Setup script and dependency list exist.
- `.env.example` includes LinkedIn, Telegram, Google Calendar placeholders.
- `.gitignore` protects secrets, DB, logs, Playwright sessions, local data.
- SQLite schema exists and `data/outreach.db` is initialized.
- BNI PDF parsed into DB: 725 prospects.
- Voice samples load: 20 samples.
- CLI help works.
- `python -m compileall outreach` passes in venv.
- Dry-run candidate batch works:
  ```bash
  ./.venv/bin/python -m outreach dry-run-batch --limit 5 --markdown
  ```
- Telegram bot token status previously worked after adding `certifi`:
  - Bot identified as `@STAI_LinkedIn_Bot`.
  - `TELEGRAM_BOT_TOKEN` and `TELEGRAM_OPERATOR_USER_ID` are set in `.env`.
- Research/opener prompts include latest hard rules:
  - No fake post references.
  - Name-only LinkedIn search route.
  - Reject uncertain matches.
  - Avoid AI competitors.
  - No BNI/source mention in opener.
  - No SkillTrainer AI pitch in opener.
  - Hook-led relaxed tone.

Database status at inspection:

```text
prospects: 725
research_rows: 1
briefs: 1
threads: 1
messages: 1
audit_log: 26
do_not_contact: 0
enrichment_status:
  found: 1
  pending: 724
```

Stored LinkedIn URL:

```text
id 34, Deni Temirov, Erzy SDN BHD, https://www.linkedin.com/in/temirovd
```

## 6. Broken Or Unfinished Work

High-priority unfinished:

1. Telegram approval queue is not implemented.
   - No polling loop.
   - No `/start`, `/queue`, `/research`, `/draft`, `/pause`, `/resume`, `/report`.
   - No inline buttons.
   - No authorization check for inbound users.
   - No queue rendering of drafts.

2. LinkedIn send path is not implemented.
   - There is no safe `send_approved_message(message_id)` function.
   - Required design: send tool must accept only a Telegram-approved DB message ID, never raw text.

3. LinkedIn enrichment/search is too naive.
   - `outreach/linkedin/search.py` searches by name only but returns the first `/in/` link.
   - It does not inspect result list company/headline/location.
   - It can select wrong profiles.
   - Must be replaced with structured result extraction and validation workflow.

4. Profile/activity scraping is partial.
   - `outreach/linkedin/profile.py` only attempts profile headline/location and last N posts via activity page.
   - It does not capture comments/reposts/engagement separately.
   - It does not prove source type (`post`, `comment`, `repost`, `engagement`), which the new prompt expects.

5. Research brief generation is manual.
   - `prompt-brief` prints a prompt.
   - Claude Code must generate the brief in chat, then save via `save-brief`.
   - No automation because v1 forbids background/API LLM calls.

6. Opener drafting is manual.
   - `prompt-opener` prints prompt plus brief plus voice samples.
   - Claude Code must produce opener, then save via `save-opener`.
   - No automatic LLM/API generation.

7. Telegram test delivery was not fully revalidated after user pressed Start.
   - Previous `telegram-status` succeeded before user started bot.
   - `telegram-test` initially failed with `Bad Request: chat not found`.
   - User then pressed Start.
   - Codex could not rerun due tool/network usage limit.
   - Claude Code should rerun:
     ```bash
     ./.venv/bin/python -m outreach telegram-test
     ```

8. Hashtag discovery is specified but absent.
   - `hashtags.txt` does not exist.
   - No code to read LinkedIn hashtag pages.

9. Calendar integration is specified but absent.
   - No Google OAuth implementation.
   - No Calendar API dependency.
   - No `/connect-calendar`.

10. Tests/linting are absent.
   - No `tests/`.
   - No `pytest`, `ruff`, `mypy`, or CI config.

## 7. Known Bugs, Edge Cases, And Risks

LinkedIn/profile risks:

- LinkedIn automation risks account restriction. Keep rate limits conservative.
- `search_for_profile()` returns first profile link and may pick wrong person. This directly violates the intended result-list validation rule until fixed.
- User specifically corrected earlier behavior: do not search `name + company`; search name only, then inspect result list for company/headline/location match.
- Avoid drafting if current company/headline/location cannot be matched confidently.
- Reject profiles outside Malaysia/SEA. This was prompted by a bad earlier candidate in Dubai.
- Avoid AI-related companies/direct competitors. This was prompted by AI-provider candidates being too close to SkillTrainer AI.
- Headless LinkedIn session checks can fail due LinkedIn redirects, captcha, account warnings, or browser/profile conflicts.
- Python Playwright persistent context may conflict if MCP or another Chromium instance is using the same `.playwright-session`.

Messaging/content risks:

- Biggest quality risk: messages sounding robotic, formal, or like a consultant questionnaire.
- Current tone rule: hook-led, relaxed, founder-to-founder, easy-to-answer question.
- Hard anti-fabrication rule: do not mention posts/comments/reposts unless captured in research data.
- Do not mention BNI or source list in openers.
- Do not pitch SkillTrainer AI in opener.
- Do not ask for a meeting in opener.
- Introduce SkillTrainer AI only after relevant pain is surfaced.
- Pricing, contract terms, refunds, SLAs, data/privacy, and security questions must be escalated to Zico (`needs_attention=1`), not answered by bot.

Telegram/security risks:

- Telegram bots are not end-to-end encrypted. They are cloud chats.
- Public users may find `@STAI_LinkedIn_Bot`, but implementation must reject all user IDs except `TELEGRAM_OPERATOR_USER_ID`.
- Current `telegram_client.py` has no inbound authorization logic because no polling loop exists yet.
- `.env` contains real token and user ID; do not print or commit.

Data/privacy risks:

- `data/outreach.db`, BNI PDF, and `.playwright-session/` contain sensitive/local personal/session data. They are ignored by git.
- Audit log currently stores `target` values that can include URLs. This conflicts partly with the privacy goal "logs without full LinkedIn URLs where avoidable." Consider changing future logs to prospect IDs or hashed targets.
- Data encryption is assumed via macOS FileVault, not application-level DB encryption.

Implementation risks:

- `tf-playwright-stealth` is installed but unused.
- `certifi` was added to fix Telegram SSL certificate verification on macOS/local venv.
- The README phase table is now stale: it says LinkedIn search/profile is "coming next" even though CLI code exists. Update user-facing status after stabilizing.
- Many files are untracked. A clean commit/branch should be made before major migration work.

## 8. Required Environment Variables And Setup Steps

Required now:

- `TELEGRAM_BOT_TOKEN`: token from `@BotFather`. Set in `.env`.
- `TELEGRAM_OPERATOR_USER_ID`: numeric Telegram user ID from `@userinfobot`. Set in `.env`.

Optional/defaulted:

- `PLAYWRIGHT_USER_DATA_DIR`: default `.playwright-session/`.
- `DB_PATH`: default `data/outreach.db`.
- `VOICE_SAMPLES_DIR`: default `files/voice-samples/`.
- `DATA_DIR`: default `data/`.
- `LOGS_DIR`: default `logs/`.

Planned future:

- `GOOGLE_OAUTH_CREDENTIALS_PATH`: not used yet.
- `GOOGLE_OAUTH_TOKEN_PATH`: not used yet.

Initial setup from a fresh clone/folder:

```bash
cd "/Users/zicong/Desktop/SkillTrainer AI/LinkedIn Outreach Agent"
chmod +x setup.command
./setup.command
```

Manual setup alternative:

```bash
cd "/Users/zicong/Desktop/SkillTrainer AI/LinkedIn Outreach Agent"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
python -m outreach init-db
```

Telegram setup:

1. In Telegram, create a bot with `@BotFather`.
2. Put token in `.env` as `TELEGRAM_BOT_TOKEN=...`.
3. Get numeric ID from `@userinfobot`.
4. Put ID in `.env` as `TELEGRAM_OPERATOR_USER_ID=...`.
5. Open the bot chat and press Start/send `/start`.
6. Run:
   ```bash
   ./.venv/bin/python -m outreach telegram-status
   ./.venv/bin/python -m outreach telegram-test
   ```

LinkedIn setup:

```bash
./.venv/bin/python -m outreach linkedin-login
```

This opens a visible browser. User logs in manually. Password/2FA never pass through the code.

Check LinkedIn session:

```bash
./.venv/bin/python -m outreach linkedin-status
```

## 9. Commands To Install, Run, Test, Lint, Debug

Install/setup:

```bash
cd "/Users/zicong/Desktop/SkillTrainer AI/LinkedIn Outreach Agent"
./setup.command
```

Activate venv:

```bash
source .venv/bin/activate
```

Initialize DB:

```bash
./.venv/bin/python -m outreach init-db
```

Parse BNI PDF:

```bash
./.venv/bin/python -m outreach parse-bni "data/BNI_Malaysia_Potential_Clients.xlsx - All Candidates.pdf"
```

Check available CLI:

```bash
./.venv/bin/python -m outreach --help
```

Compile/check Python syntax:

```bash
./.venv/bin/python -m compileall outreach
```

Verify voice samples:

```bash
./.venv/bin/python -m outreach voice-samples
```

Generate dry-run pre-validation batch:

```bash
./.venv/bin/python -m outreach dry-run-batch --limit 5 --markdown
```

Telegram status/test:

```bash
./.venv/bin/python -m outreach telegram-status
./.venv/bin/python -m outreach telegram-test
```

LinkedIn login/status:

```bash
./.venv/bin/python -m outreach linkedin-login
./.venv/bin/python -m outreach linkedin-status
```

Read a LinkedIn profile:

```bash
./.venv/bin/python -m outreach linkedin-profile "https://www.linkedin.com/in/<slug>" --posts 5 --json
```

Enrich/research one prospect:

```bash
./.venv/bin/python -m outreach enrich 421
./.venv/bin/python -m outreach research 421
```

Generate prompt for Claude Code to create a research brief:

```bash
./.venv/bin/python -m outreach prompt-brief 421
```

Save brief after Claude Code writes it:

```bash
./.venv/bin/python -m outreach save-brief 421 path/to/brief.md
```

Generate prompt for Claude Code to draft opener:

```bash
./.venv/bin/python -m outreach prompt-opener 421
```

Save opener:

```bash
./.venv/bin/python -m outreach save-opener 421 path/to/opener.txt
```

Inspect DB counts:

```bash
sqlite3 data/outreach.db "select 'prospects', count(*) from prospects union all select 'research_rows', count(*) from research union all select 'messages', count(*) from messages;"
```

No lint/test suite currently exists. Recommended next additions:

```bash
pip install pytest ruff
mkdir -p tests
```

Then add tests for pure functions before browser/Telegram work.

## 10. Exact Next Steps For Claude Code

Priority 0: Protect the current state.

1. Do not commit `.env`, `.playwright-session/`, `data/`, or logs.
2. Run `git status --short`.
3. Consider creating a migration branch:
   ```bash
   git switch -c claude/handover-continuation
   ```
4. Commit or at least preserve current untracked code/docs before large refactors.

Priority 1: Verify setup in VS Code/Claude Code.

1. Run:
   ```bash
   ./.venv/bin/python -m compileall outreach
   ./.venv/bin/python -m outreach --help
   ./.venv/bin/python -m outreach voice-samples
   ./.venv/bin/python -m outreach dry-run-batch --limit 5 --markdown
   ```
2. Run Telegram test now that user pressed Start:
   ```bash
   ./.venv/bin/python -m outreach telegram-status
   ./.venv/bin/python -m outreach telegram-test
   ```
3. If `telegram-test` still says `chat not found`, verify `TELEGRAM_OPERATOR_USER_ID` and make sure the user started `@STAI_LinkedIn_Bot`.

Priority 2: Implement Telegram authorization and polling foundation.

Add an operator-only Telegram update loop. Suggested files:

- `outreach/telegram_client.py`: add `get_updates(offset)`, `answer_callback_query`, `send_message`, `edit_message_text`.
- New `outreach/telegram_bot.py`: command handling and authorization.
- `outreach/__main__.py`: add command `telegram-poll`.

Required behavior:

- Every inbound update must compare `from.id` to `TELEGRAM_OPERATOR_USER_ID`.
- Unauthorized users get either no response or a generic rejection. Do not leak project details.
- Implement `/start` to show system status.
- Implement `/queue` to show draft/pre-validation queue count.
- No LinkedIn send action yet.

Priority 3: Replace naive LinkedIn search.

Current bug: `search_for_profile()` returns first `/in/` link. Replace with result-list extraction:

- Search by name only.
- Extract top 10 people results with:
  - profile URL
  - displayed name
  - headline
  - location
  - connection degree if visible
- Add matching/validation logic:
  - strong name match
  - company/headline contains expected company or plausible role/category
  - location in Malaysia/SEA
  - reject AI-provider/competitor terms
  - reject uncertain matches
- Return structured candidates, not just one URL.
- Keep a manual-review mode if validation is uncertain.

Suggested new functions:

```python
def search_people_results(name: str, limit: int = 10) -> list[SearchResult]: ...
def validate_result_against_prospect(result: SearchResult, prospect: dict) -> ValidationDecision: ...
```

Do not auto-store a LinkedIn URL if the match is uncertain.

Priority 4: Improve research capture.

Current `read_profile()` only returns `posts: list[str]`; prompt expects post/comment/repost/engagement source types.

Improve returned structure to:

```json
{
  "url": "...",
  "name": "...",
  "headline": "...",
  "location": "...",
  "activity": [
    {"type": "post", "text": "...", "url": null, "captured_at": "..."}
  ]
}
```

Then update `prompts/research_brief.md` and `outreach/research.py` accordingly.

Priority 5: Build draft queue display in Telegram.

After `save-opener`, drafts live in `messages` table. Implement:

- `/drafts` or `/queue` command to list `messages.status='draft'`.
- Render prospect name/company, research brief summary, draft content.
- Inline buttons: Approve & Send, Edit, Skip, Defer.
- For now, Approve should mark status `approved` only. Do not send LinkedIn yet.

Priority 6: Only after approval queue works, implement LinkedIn send path.

Hard requirement:

- Function must accept `message_id`.
- Load DB row where `status='approved'` and `approved_via='telegram'`.
- Reject raw text.
- Reject if message not approved.
- Respect daily rate limit.
- Log action.
- Mark sent only after successful browser send.

Priority 7: Add tests.

Start with pure tests:

- `clean_post_text`
- `_normalize_profile_url`
- rate limiter math
- BNI parser deduplication
- dry-run candidate filtering
- Telegram config validation

## 11. Files Claude Should Inspect First

Read these in order:

1. `HANDOVER_CLAUDE_CODE.md`
2. `files/CLAUDE.md`
3. `files/PRD.md`
4. `README.md`
5. `outreach/__main__.py`
6. `outreach/db/schema.sql`
7. `outreach/config.py`
8. `outreach/telegram_client.py`
9. `outreach/linkedin/search.py`
10. `outreach/linkedin/profile.py`
11. `outreach/research.py`
12. `prompts/research_brief.md`
13. `prompts/opener.md`
14. `.env.example`
15. `.mcp.json`

Do not inspect `.env` by printing it. If needed, check only whether keys are set.

## 12. Assumptions, Constraints, And Design Decisions Already Made

Non-negotiable constraints:

- Human approval required before any send.
- Telegram is the approval interface.
- LinkedIn actions must remain local and modest-volume.
- No LLM APIs in v1. Claude Code/Claude Pro only.
- No `ANTHROPIC_API_KEY`, OpenAI, Google, Azure OpenAI, or background LLM drafting.
- No auto-send, auto-connect, auto-react.
- No source-list/BNI mention in openers.
- No SkillTrainer AI/product pitch in openers.
- No meeting ask in opener.
- Pricing/contracts/privacy/security/commercial commitments are escalation-only.

Prospecting decisions already made:

- Search LinkedIn by name only.
- Validate from result list against company/headline/location.
- Reject uncertain matches.
- Reject outside Malaysia/SEA unless target geography is proven.
- Avoid AI-provider/AI automation/chatbot/AI training/direct competitor profiles.
- Prioritize non-AI companies likely to buy workforce AI training.
- For dry runs, stop when requested number of valid prospects is selected.

Tone decisions already made:

- Messages should feel human, relaxed, and founder-to-founder.
- Use hooks, not boring interview questions.
- Use market truths when no good recent activity exists.
- Use recent posts/engagement only when actually captured.
- Never fabricate a post reference.

Local state assumptions:

- `.env` exists and contains Telegram token/user ID.
- `.playwright-session/` exists and may contain LinkedIn login state.
- `data/outreach.db` exists and contains parsed BNI data.
- `files/voice-samples/` contains 20 RTF samples.
- User is non-technical; explain terminal/setup steps plainly.

## Current Git/Working Tree Notes

At inspection, `git status --short` showed:

```text
 M .gitignore
 M files/CLAUDE.md
 M files/PRD.md
?? .codex/
?? .env.example
?? .mcp.json
?? README.md
?? files/voice-samples/
?? outreach/
?? prompts/
?? requirements.txt
?? setup.command
```

Important: `HANDOVER_CLAUDE_CODE.md` was added after that status snapshot and
will also be untracked until committed.

`data/`, `.env`, `.venv/`, `.playwright-session/`, `.playwright-mcp/`, and
`logs/` are ignored by `.gitignore`.

Before moving to a new environment, decide whether to commit the project files
that are currently untracked. Do not commit local secrets or local data.
