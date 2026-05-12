# LinkedIn Outreach Automation — Agent Instructions

## Read This First

This project helps the founder run LinkedIn cold outreach for SkillTrainer AI.
It surfaces prospects, gathers lightweight research, drafts human-sounding
messages, and prepares reply/meeting workflows.

**The system is drafting and approval infrastructure. It is not an autonomous
sender. No LinkedIn message, connection request, reply, reaction, or calendar
booking confirmation may happen without the operator's explicit Telegram
approval.**

Before making product or implementation decisions, read:

1. `files/PRD.md` — product requirements and rationale
2. This file — implementation constraints and operating rules
3. `README.md` — current user-facing setup/status

When docs conflict, follow the stricter safety rule. If product behavior is
unclear, ask before implementing.

## Operator Context

The operator is a founder, not a software engineer.

When working on this project:

- Explain setup and tradeoffs in plain English.
- Walk through outside-editor steps one at a time.
- Say explicitly when the operator must sign into a service, paste a token, or
  keep the Mac awake.
- Prefer simple, well-supported local tools over clever or fragile systems.
- Do not hide compliance, account-safety, or privacy tradeoffs.

## Non-Negotiable Rules

### 1. Human Approval Before Any Send

Every outbound LinkedIn action must be gated by Telegram approval.

Required:

- Every opener, reply, follow-up, closer, and connection request goes to the
  Telegram approval queue first.
- The final send path accepts only a Telegram-approved queue/message ID.
- The send path must reject raw message text.
- The bot must show Approve & Send, Edit, Skip, and Defer controls for drafts.

Forbidden:

- Auto-sending messages, replies, reactions, or connection requests.
- "Just this once" bypasses.
- Sending from an in-Claude-Code prompt.
- Any code path where the LLM can provide raw text directly to a send action.

If the operator asks for autonomous sending, explain the account-safety risk
and keep the Telegram approval gate.

### 2. Claude Pro Only, No LLM APIs in v1

All LLM work in v1 happens interactively inside Claude Code using the
operator's Claude Pro subscription.

Forbidden in v1:

- Anthropic API calls, SDKs, raw HTTP calls, or `ANTHROPIC_API_KEY`.
- OpenAI, Google, Azure OpenAI, or other paid LLM providers unless the operator
  explicitly approves a v2 change with a documented cost cap.
- Scheduled/background LLM calls.
- Overnight/weekend drafting without the operator present.

Allowed:

- Scheduled prospect surfacing that does not call an LLM.
- Local data gathering via Playwright MCP.
- Prompt generation files that Claude Code reads during an interactive session.

If the operator hits Claude Pro limits, pause cleanly and tell them to resume
after the limit resets. Do not add an API fallback.

### 3. LinkedIn Account Safety

LinkedIn's terms prohibit automated platform interaction. The project reduces
risk through modest volume, local browser sessions, audit logs, and human
approval.

Use Playwright MCP only from the operator's local machine and real logged-in
session. Never ask for, store, transmit, or log LinkedIn passwords or 2FA codes.

Allowed browser actions for v1:

- Read profile
- Read posts
- Read comments
- Read inbox
- Search LinkedIn by name, then validate company/headline/location from the
  result list
- Send a Telegram-approved message
- Send a Telegram-approved connection request

Do not expose generic browser tools such as arbitrary page evaluation or
free-form click/type control to the writing or reply path.

Before LinkedIn runs:

- Check the session is authenticated.
- Abort if LinkedIn shows warnings, captcha, unusual-activity prompts, or
  account restrictions.
- Respect rate limits in code, not only in prompts.
- Log actions locally without prospect names, message text, or full LinkedIn
  URLs where avoidable.

Starting hard caps until tuned with the operator:

- Connection requests: max 15/day
- Profile-view budget: max 80/day
- Name search cost: 2 profile-view budget units
- Messages sent: max 25/day
- Add jitter/human pacing between browser actions

### 4. Voice Fidelity

Generated messages must sound like the founder typing naturally, not like a
polished sales template.

Voice source of truth:

- Folder: `files/voice-samples/`
- Current format: 20 `.rtf` files
- The writing flow must read these samples for every drafting session.

Forbidden message patterns:

- "I hope this message finds you well" or variants
- Heavy em-dash rhythm
- Tricolon openers
- Overly polished sentence symmetry
- Buzzword stacking
- Formal sign-offs like "Best regards" or "Warm regards"
- Hard pitch on first contact
- Wall-of-text explanations
- Perfectly corporate grammar in every sentence

Required message patterns:

- Natural contractions
- One core thought per message
- Small human imperfections
- Short, phone-typed feel
- Low-friction ask at the end of openers
- Hook-led opening: a sharp observation, pattern, or mild point of view before
  asking anything.
- Relaxed, approachable rhythm. It should feel like a real LinkedIn chat, not
  a discovery-call script.
- Questions should create curiosity or invite a quick opinion, not sound like a
  checklist.
- Research-led hook selection: recent posts, comments, reposts, or engagement
  are the preferred hook source when they are useful. If not, fall back to the
  profile/company/category, then to a role-specific market truth.

Audience angle:

- v1 targets BNI Malaysia members and adjacent Malaysia/SEA prospects in
  IT/software, training, marketing, HR, and consulting.
- Do not mention or pitch SkillTrainer AI on first contact.
- Do not mention BNI or reveal that the prospect came from a BNI/source list in
  the opener.
- Ease into AI rollouts, training challenges, workforce readiness, and
  practical business curiosity only when it follows naturally from the
  prospect's own profile/posts.
- Research process before drafting:
  1. Read visible recent posts, comments, reposts, and engagement if available.
  2. Look for suitable business hooks: client/team problems, productivity,
     hiring, training, marketing pressure, operations, customer experience, AI
     adoption, or workflow change.
  3. If a suitable recent activity hook exists, use it lightly in the opener.
  4. If recent activity is missing, generic, too personal, or not relevant,
     use a profile/company/category hook.
  5. If profile data is thin, use a founder-to-founder market-truth hook.
- Do not force a recent-post reference. A weak post hook is worse than a strong
  market-truth hook.
- Hard evidence rule: never say "saw your post", "noticed your post", "your
  recent post", or refer to a specific comment/repost unless Playwright
  research actually captured that post/comment/repost/engagement. If no
  suitable activity was captured, use profile/company/category or market-truth
  hooks without implying a post was seen.
- Prefer a soft peer-to-peer opener about what the prospect is building,
  seeing, or focused on, but lead with a hook instead of a plain question.
- Avoid boring "are clients asking for X or Y" interview-style openers unless
  there is a genuinely interesting angle behind it.
- Good openers can lightly name a tension the prospect probably feels:
  "Everyone wants faster content now, but half the battle is still making it
  sound like the brand", "Feels like hiring is the easy part compared with
  getting people productive", or "Most teams say they want AI, then freeze when
  it touches the actual workflow."
- The objective is consultative sales: qualify the prospect, introduce the
  training platform into their workforce context, and secure a face-to-face
  meeting with a potential paying client.
- Replies 1–2 should stay curious and open-ended, but they must not feel like
  an interrogation. Use light reactions, small opinions, and natural follow-ups
  to uncover business need, team size/context, AI adoption friction, training
  gaps, or urgency.
- Replies 3–4 may gradually introduce that Zico works on practical AI training
  only if the conversation naturally points to AI adoption, team readiness, or
  implementation friction.
- When introducing SkillTrainer AI, connect it directly to the pain surfaced in
  the conversation: practical workforce training, real workflows, team
  consistency, faster execution, and less random AI usage. Do not switch into a
  generic pitch.
- Once relevant pain or interest is shown, steer toward a face-to-face meeting
  rather than a vague "compare notes" conversation.

Escalate instead of drafting when the prospect asks about pricing, contracts,
refunds, SLAs, data/privacy, security, or anything commercially binding.

Prospect-fit check before drafting:

- Search LinkedIn by name first, then inspect results for company/headline fit.
- Do not rely on name match alone.
- Confirm the profile is Malaysia/SEA-based or clearly tied to the BNI Malaysia
  row.
- Reject the candidate if the best LinkedIn match is outside Malaysia/SEA
  (for example Dubai, UK, US, EU) unless the BNI row itself clearly proves they
  are operating in Malaysia/SEA.
- Default away from AI-provider companies, AI automation agencies, AI chatbot
  vendors, AI training providers, and other businesses that sound like direct
  competitors or implementation partners. They are usually poor first-priority
  paying-client prospects.
- Prioritize non-AI companies with teams or client-facing operations that could
  benefit from practical workforce AI training: marketing/creative agencies,
  HR consultancies, training companies, professional services, retail/service
  businesses, and conventional SMEs.
- If current company/headline/location cannot be matched with reasonable
  confidence, mark as uncertain and pick another prospect. Do not draft.
- For a requested dry run of N prospects, stop searching once N valid prospects
  are selected.

### 5. Privacy and Data Protection

Prospect data is third-party personal data. Treat it accordingly.

Required:

- Collect only data needed for outreach decisions.
- Store data locally in SQLite unless the operator explicitly approves another
  private storage option.
- Rely on macOS FileVault for encryption at rest; verify it before storing real
  prospect data on a new machine.
- Keep `.env`, OAuth tokens, Telegram tokens, and Playwright session paths out
  of git and logs.
- Use internal IDs in logs instead of names, URLs, or message content.
- Check do-not-contact before surfacing, drafting, or sending.
- Provide a manual deletion path for any prospect.

Retention:

- Keep active-thread data while the thread is open.
- After meeting booked, declined, ghosted > 90 days, or do-not-contact request,
  delete research/draft content and keep only minimal duplicate-prevention or
  do-not-contact records.

When in doubt, follow the strictest likely regime: Malaysia PDPA, Singapore
PDPA, EU/UK GDPR.

## Product Workflow

### Current v1 Direction

The operator should stay close to research and drafting. The 10am automation
surfaces prospects only. Research synthesis and message drafting happen when
the operator is present in Claude Code.

Daily flow:

1. Surface candidates from the BNI list and hashtag stream.
2. Enrich selected candidates with LinkedIn URLs.
3. Score/rank using cheap signals.
4. Write the day's queue locally.
5. Notify Telegram that the queue is ready.
6. When the operator is present, Claude Code gathers research and drafts.
7. Telegram approval gates every send.

No LLM call belongs in the scheduled surfacing job.

### Conversation Rules

- Never send two outbound messages to a non-responding prospect on the same
  calendar day.
- Opener + one follow-up only.
- Follow-up waits at least one day after the opener.
- If no reply one day after follow-up, close as ghosted.
- Polite "no thanks" gets a short closer for approval, then close.
- Aggressive negative or do-not-contact request gets no draft; flag NEEDS YOU,
  mark do-not-contact, and delete research data.
- Inbound after closure reopens the thread.

Reply handling:

- Detect inbound messages without LLM drafting.
- Apply a varied humanlike delay before surfacing the reply for drafting.
- Respect Malaysia business hours (UTC+8).
- Escalate ambiguous/commercial/sensitive messages instead of drafting.

### Google Calendar Rules

- Setup is through `/connect-calendar`.
- Store OAuth token paths in `.env`; do not commit tokens.
- Wait for the prospect to suggest a time.
- Check the operator's calendar free/busy.
- Do not proactively propose slots unless responding to a suggested time.
- Do not invite the prospect by email in v1.
- On approval, send the LinkedIn confirmation and create a block-only event on
  the operator's calendar.
- Event title: `LinkedIn meeting - [Prospect Name] (re: [hook])`
- Event description includes the LinkedIn thread URL.

## Architecture

Use the current codebase patterns unless there is a clear reason to change.

Current implemented foundation:

- Language: Python
- Local database: SQLite at `data/outreach.db`
- Voice samples: `files/voice-samples/`
- Prompts: `prompts/research_brief.md`, `prompts/opener.md`
- BNI source data: files under `data/`
- LinkedIn browser/session support: `outreach/linkedin/`
- Rate limits: `outreach/rate_limiter.py`
- Draft storage: `messages` table with Telegram approval pending

Planned components:

- Scheduler: daily 10:00 AM Malaysia time; prospect surfacing only
- Prospect sourcing: BNI list plus hashtag discovery; Sales Navigator is not
  used in v1
- Research module: gathers local/LinkedIn data; Claude Code synthesizes briefs
  interactively
- Writing module: prompt/reference flow, not a standalone LLM service
- Telegram cockpit: private bot, operator-only allowlist
- Send tool: queue-ID only, no raw text
- Calendar integration: Google Calendar block-only events
- Retention/deletion commands: required before live operation at scale

## Key Files

- `files/PRD.md` — full product spec
- `files/CLAUDE.md` — this instruction file
- `README.md` — operator-facing overview and current status
- `.env.example` — expected environment variables
- `.env` — local secrets only; never commit
- `files/voice-samples/` — founder voice references
- `prompts/` — Claude Code drafting/research prompt templates
- `outreach/` — Python package
- `data/outreach.db` — local database
- `logs/` — local logs; no sensitive prospect content

## Implementation Guidance

When adding features:

1. Read the PRD section for the feature.
2. Check existing code and database schema first.
3. Preserve the human approval gate structurally, not just in prompts.
4. Add tests or dry-run commands for risky behavior.
5. Keep logs privacy-safe.
6. Prefer dry-run before live LinkedIn actions.
7. Explain operator setup steps plainly.

Do not implement live sending until all of these exist:

- Telegram operator allowlist
- Approval queue with immutable queue/message IDs
- Send function rejects raw text
- Rate limiter and audit log are active
- Session health check is active
- Dry-run has been reviewed with the operator

## Risky Requests

Stop and explain the risk before proceeding if a request would:

- Auto-send or bypass Telegram approval
- Add API-backed or background LLM drafting
- Add `ANTHROPIC_API_KEY` or another LLM provider
- Increase LinkedIn volume beyond conservative caps
- Store credentials insecurely
- Use a cloud/shared browser session
- Expose generic browser controls to writing/reply logic
- Allow non-operator Telegram users
- Send calendar invites to prospects
- State pricing or commercial commitments
- Skip do-not-contact, deletion, retention, or privacy checks
- Log prospect names, URLs, message content, or secrets

Offer the nearest safe alternative.

## Open Decisions

Resolve these before live operation:

- Backup plan if LinkedIn restricts the account
- Final hourly/daily Playwright caps after early testing
- Hashtag list after first 30 days of results
- Exact voice-fidelity scorecard for approving drafts
- Criteria for any post-v1 move from Claude Pro interactive drafting to API
  automation
