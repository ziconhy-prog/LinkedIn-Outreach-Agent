# LinkedIn Outreach Automation — Claude Code Instructions

## Project Overview

This project is a LinkedIn cold outreach automation for an AI training platform.
It surfaces prospects, researches them, drafts personalized human-sounding
messages, and handles reply conversations toward booking a meeting on Google
Calendar. **The operator approves every message before it sends. The system
never sends anything autonomously.**

For the full product spec, read `PRD.md` first.

## Operator Context

The operator is a founder, **not a software engineer**. When working on this
project:
- Default to plain-English explanations of what you're doing and why
- Walk through setup steps one at a time
- Avoid jargon unless you also explain it
- When you make architectural choices, briefly justify them in plain language
- If a step requires the operator to do something outside the editor (install
  something, sign into a service, paste a key somewhere), say so explicitly
- Prefer simple, well-supported tools over clever or cutting-edge ones

## Critical Constraints

### Compliance and account safety
LinkedIn's Terms of Service prohibit automated interaction with the platform.
This system mitigates that risk by being **drafting infrastructure only**:

- **Never write code that sends a LinkedIn message, connection request, or reaction without an explicit human click.**
- Never write code that auto-replies, auto-likes, or auto-connects.
- All LinkedIn actions must route through an approval queue.
- The system runs from the founder's real account at modest daily volume.

If at any point a feature request would cross this line, flag it before implementing.

### Voice fidelity (read this before writing any message-generation code)
The single most important quality bar in this project is that generated
messages do not read as AI-written. The agent's output must sound like a real
founder typing on their phone.

**Forbidden patterns in generated messages:**
- Em-dash-heavy rhythm
- Tricolon openers (three parallel adjectives or clauses)
- "I hope this message finds you well" or any variant
- Overly polished symmetry between sentences
- Buzzword stacking ("synergize," "leverage," "scalable," etc.)
- Formal sign-offs ("Best regards," "Warm regards," "Looking forward to hearing")
- Over-explaining or wall-of-text messages
- Perfect grammar in every sentence

**Required patterns:**
- Natural contractions (it's, you're, I'm, don't)
- Occasional sentence fragments
- One core thought per message
- Small imperfections — the kind a human leaves in
- Low-friction asks at the end of openers (a question, a reaction prompt, never a hard pitch)

When you build the prompt for the writing agent, include negative examples (the
forbidden patterns above) and positive examples (sample messages from the
operator). Test outputs against these explicitly.

### Human-in-the-loop is non-negotiable
Every message — opener, reply, follow-up — goes through an approval queue
before sending. Even when the user asks for "just send it automatically for
this one," push back. This rule is the entire safety story of the project.

### Reply timing
The conversational agent must wait a varied, humanlike interval (typically 20
minutes to a few hours, depending on time of day) before drafting a reply. It
is never instant. When implementing this, randomize within sensible bounds and
respect Malaysian business hours (UTC+8).

### LLM usage — Pro subscription only, no API in v1 (hard rule)
This project runs **entirely on the operator's Claude Pro subscription** for
all LLM work. There is no Anthropic API key in v1, and no scheduled or
background LLM calls.

What this means for how you build:

- **Do not write code that calls the Anthropic API directly.** No
  `@anthropic-ai/sdk`, no `anthropic` Python package, no raw HTTP calls to
  api.anthropic.com.
- **Do not add `ANTHROPIC_API_KEY` to `.env` or any config file.** If the
  operator pastes one in by mistake, flag it and remove it.
- **Do not add other paid LLM providers** (OpenAI, Google, Azure OpenAI,
  etc.) without an explicit operator decision and a documented cost cap.
- **The 10am scheduled job does only:** prospect surfacing via Playwright
  MCP, scoring/ranking, writing the day's list to local storage, and
  notifying the operator that the queue is ready. No LLM calls of any kind.
- **All research, drafting, and reply generation happens interactively**
  inside Claude Code, when the operator is present and working the queue.
  Claude Code uses the operator's Pro subscription automatically.
- **Pro 5-hour limits apply.** If the operator hits the limit mid-session,
  pause cleanly and tell the operator when limits reset. Don't error out and
  don't try to fall back to an API.

Practical implications for the codebase:

- The "drafting module" is not a service that runs on its own. It's a set of
  prompts and reference files (voice samples, brief format) that Claude Code
  reads in-session to generate drafts.
- The "research module" similarly: gather data with Playwright MCP and
  store it locally; the LLM synthesis happens when the operator opens the
  prospect in Claude Code.
- The "reply agent" is also operator-triggered. When a prospect replies,
  the system queues the reply for the operator to review next time they
  open Claude Code. The "humanlike delay before drafting" still applies —
  but the delay is between when the reply arrives and when it appears in
  the operator's queue, not when an autonomous agent drafts it.

If the operator ever asks to "automate this so it runs overnight" or
"connect an API key so it can draft without me," push back and refer them to
the v2 conditions in the PRD. Don't quietly add the capability.

### Playwright MCP — browser automation rules
This project uses **Playwright MCP** as the LinkedIn access mechanism. Treat
the browser-driving capability as powerful and constrained:

- **Local only.** Playwright MCP runs on the operator's machine. Never propose
  cloud-hosted browser sessions or shipping the founder's logged-in profile to
  a remote server.
- **No credentials in code.** The agent uses an existing browser session the
  operator has logged into manually. Never ask for, store, or transmit
  LinkedIn passwords or 2FA codes.
- **Allowed-actions list.** Only expose specific, narrowly-scoped tools to the
  agent: read a profile, read posts, read inbox, draft a message, send an
  approved message ID. Do not expose generic "click anywhere / type anywhere"
  capabilities to the LLM.
- **Rate limits at the tool layer.** Enforce daily/hourly caps in code, not in
  prompts. Hard limits should sit below LinkedIn's known soft thresholds.
  Suggested starting points (to be tuned with the operator before going live):
  - Connection requests: ≤ 15/day
  - Profile views: ≤ 80/day
  - Messages sent: ≤ 25/day
  - Random jitter between actions (humanlike pacing)
- **Audit trail.** Every Playwright MCP action is logged with timestamp, action
  type, and target. Logs are kept locally and reviewable by the operator.
- **Sending requires approval queue ID.** The "send message" tool must take a
  reference to a queue entry the operator has approved — it must not accept
  raw message text. This makes it structurally impossible for the agent to
  send something the operator hasn't seen.
- **Session health checks.** Before any run, verify the browser session is
  authenticated and the account shows no warnings. Abort if anything looks off.

### Data protection and privacy (read before writing any data-handling code)
Prospect data is personal data of third parties. Treat it accordingly.

- **Minimize collection.** Pull only what the research module actually uses.
  Don't scrape entire profiles "just in case."
- **Local-first storage.** Prospect data, drafts, threads, and research stay
  in a local database (e.g., SQLite) or a private database under the
  operator's control. No third-party CRMs, analytics tools, or "send to a
  cloud spreadsheet" shortcuts in v1.
- **Encryption at rest.** Whatever database is chosen must support encryption
  at rest. Configure it; don't skip it.
- **No prospect data in logs.** Logs may reference prospects by internal ID,
  not by name, profile URL, or message content. If you need to debug
  message-quality issues, route the offending content through a separate
  reviewable artifact, not the standard log stream.
- **LLM privacy.** When sending prospect content to the LLM for research or
  drafting, use a provider with a documented zero-retention or no-training
  policy (Anthropic API has settings for this — verify and enable). Never
  send full unredacted profile dumps if a summary suffices.
- **Retention policy.** Active prospects: kept while the thread is open.
  Closed prospects (meeting booked, declined, or silent > 90 days): research
  and drafts deleted, only a minimal duplicate-prevention record kept.
- **Do-not-contact list.** If a prospect asks not to be contacted, mark them
  permanently do-not-contact and delete their research data. The system must
  check this list before surfacing or acting on any prospect.
- **Deletion on request.** Build a simple manual command from day one that
  takes a prospect identifier and removes all data associated with them.
- **Secrets handling.** API keys, session paths, and any auth tokens live in
  `.env`. `.env` is in `.gitignore`. Never commit it. Never log its values.
  Never paste it into chat outputs.
- **Jurisdictional awareness.** Prospects in Malaysia are covered by PDPA;
  prospects in EU jurisdictions by GDPR; prospects in Singapore by their PDPA.
  When in doubt, default to the strictest applicable standard.

## Architecture (high level — fill in as we build)

- **Scheduler:** runs daily at 10:00 AM Malaysia time (UTC+8). Surfaces
  prospects only — does **not** make LLM calls.
- **Prospect sourcing:** LinkedIn Sales Navigator via **Playwright MCP** (local browser automation)
- **Research module:** data gathering via Playwright MCP and web search;
  LLM synthesis happens interactively in Claude Code on the operator's Pro subscription
- **Writing module:** prompts and voice references that Claude Code reads
  in-session; no standalone service, no API calls
- **Approval queue:** CLI-style review flow rendered inside the Claude Code session (v1). Local-only, no third-party services. May graduate to a local web app in v2 if needed.
- **Calendar integration:** Google Calendar API for availability and event creation
- **Storage:** local encrypted database (SQLite with encryption, or similar)
  for prospects, drafts, threads, status
- **MCP servers used:** Playwright MCP (browser), Google Calendar MCP or direct API (calendar)
- **LLM:** Claude Pro subscription, accessed via Claude Code only. No API in v1.

## Conventions (to fill in as decisions are made)

- Language: TBD (likely Python or TypeScript — discuss with operator before choosing)
- Secrets: stored in a `.env` file at project root; never committed; never logged
- Logs: should never include full prospect names, message content, or LinkedIn URLs in plain text where avoidable
- Commits: use conventional commits (feat:, fix:, docs:, chore:)

## Commands

To be added as the project develops. Examples we'll likely have:
- A command to dry-run the daily prospect surfacing
- A command to test a single prospect end-to-end
- A command to generate a sample opener against a test profile

## Key Files

- `PRD.md` — full product requirements and rationale (read this for context on any feature decision)
- `CLAUDE.md` — this file
- `.env.example` — required environment variables (to be created)
- `voice-samples/` — folder of real messages the founder has written, used as
  voice reference for the writing module (to be populated)

## Out of Scope (don't suggest these unless asked)

- Email outreach
- Other channels (X, Instagram, WhatsApp)
- Multi-operator features
- Built-in CRM
- Any form of auto-sending
- Analytics dashboards beyond basic counts

## When the Operator Asks for Something Risky

If a request would:
- Auto-send any message
- Bypass the approval queue
- Increase LinkedIn volume beyond conservative caps
- Store credentials insecurely or pass LinkedIn passwords through the agent
- Run Playwright MCP against a cloud-hosted or shared browser session
- Expose generic "click anywhere / type anywhere" browser tools to the LLM
- Send unredacted prospect data to a third-party service that isn't the
  approved LLM provider
- Skip encryption, retention limits, or do-not-contact checks
- Skip the voice-fidelity checks
- Add an Anthropic API key, third-party LLM provider, or any background/
  scheduled LLM call (v1 is operator-in-the-loop, Pro only)
- "Automate" any drafting step so it runs without the operator present

…stop and explain the risk in plain English before doing it. Suggest a safer
alternative. The operator has explicitly asked for this safety net.

## Open Questions to Resolve Before Building

1. ~~How will the system access Sales Navigator data?~~ → **Resolved:** Playwright MCP (local browser automation against the founder's logged-in session).
2. ~~Where does the approval queue live?~~ → **Resolved:** CLI-style review flow inside the Claude Code session itself for v1. Keeps prospect data local, no extra services to build or maintain. Revisit local web app in v2 if review ergonomics justify it.
3. What's the founder's voice baseline? Need 20+ sample messages from the founder to ground the writing module.
4. What's the budget tolerance for LLM costs per prospect?
5. What's the contingency if the LinkedIn account is restricted?
6. Which local database for storage? (SQLite with SQLCipher is a strong default — confirm with operator.)
7. Concrete starting numbers for daily/hourly Playwright MCP rate limits — confirm with operator before first live run.
8. Confirm Anthropic API zero-retention settings are enabled for prospect data calls.

Resolve these before writing significant code. They drive the architecture.
