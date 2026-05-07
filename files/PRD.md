# LinkedIn Outreach Automation — PRD

**Status:** Draft
**Last updated:** 2026-05-06
**Version:** 0.1

## 1. Overview

A LinkedIn cold outreach automation for an AI training platform that upskills the
general workforce on AI knowledge. The system finds high-fit prospects across
Malaysia and Southeast Asia, researches them deeply, drafts personalized
human-sounding messages, and carries reply conversations forward toward a booked
meeting — with the operator (the founder) as the final approver on every message.

The system is **drafting and research infrastructure**, not an autonomous sender.
The human always presses send.

## 2. Problem Statement

Cold outreach on LinkedIn is high-leverage but time-expensive. Doing it well
requires real research per prospect, a personalized opener, and ongoing reply
handling — none of which scales without help. Existing tools either send generic
spam (which gets ignored or flagged) or require so much manual work they don't
save time. The founder needs research and drafting leverage without losing the
human voice or risking the account.

## 3. Goals & Non-Goals

### Goals
- Surface 10–20 high-fit prospects per workday, ranked by buying signal strength
- Produce a research brief per prospect that the founder would have written themselves
- Draft opening messages that are indistinguishable from the founder's own writing
- Handle reply conversations end-to-end (drafting only) until a meeting is booked
- Book the meeting on Google Calendar once the prospect agrees
- Keep the founder's LinkedIn account safe — modest volume, human approval, real account

### Non-Goals
- No fully automated sending. Every message is approved by the operator first.
- No mass outreach. Quality over volume — daily caps stay modest.
- No multi-user / team features in v1. Single operator.
- No CRM replacement. This system feeds outreach; pipeline lives elsewhere if needed.
- No paid ad targeting, no email outreach, no other channels in v1.

## 4. Target Users

### Operator (the user of this system)
The founder running outreach. Approves every message, edits when needed, handles
escalations the agent flags.

### Prospects (two parallel personas being reached out to)

**Persona A — L&D and HR leaders**
- Titles: Head of L&D, Head of People, CHRO, L&D Director
- Pain: operational reality of upskilling teams on AI
- Angle: practical L&D pain, how the platform reduces that load

**Persona B — C-suite executives**
- Titles: CEO, COO, CHRO
- Pain: owning the strategic narrative around AI adoption, holding the budget
- Angle: strategic AI adoption, workforce-readiness as competitive position

## 5. Core Workflow

### 5.1 Daily prospect surfacing
- Runs every workday at **10:00 AM Malaysia time (UTC+8)**
- Pulls 10–20 prospects from LinkedIn Sales Navigator
- Geography: Malaysia + Southeast Asia
- Sourced from Sales Navigator via Playwright MCP browser session
- Scores and ranks prospects on signals:
  - Recent LinkedIn posts about AI, upskilling, or digital transformation
  - Recent job change into a target role
  - Public company announcements about AI initiatives
  - Active hiring for AI-related positions
- **Important:** the scheduled job at 10am does **only** the surfacing — it
  pulls and scores the prospect list and writes it to local storage. It does
  not make any LLM calls. The operator is then notified (e.g., a desktop
  notification or simple log entry) that the day's list is ready for review.

### 5.2 Per-prospect research
For each surfaced prospect, the system pulls:
- Their last 10–20 LinkedIn posts and comments
- Recent company news
- Podcast or article appearances
- Mutual connections

It feeds all of this to an LLM that returns a structured brief:
- What the person cares about professionally
- Any public engagement with AI, L&D, or workforce-development topics
- The single strongest hook for an opening message

### 5.3 Opener drafting
- Tailored to title and seniority (Persona A vs Persona B angle)
- **Default mode:** warm, conversational
- **Hook mode:** if research surfaces a relevant post/article/topic the prospect
  has engaged with around AI or workforce development, the opener leads with
  that specific context instead of a generic template
- Closes with a **low-friction ask** — a reaction, a quick question, or a short
  chat. Never a hard demo pitch.

### 5.4 Approval queue
The operator sees, side by side:
- The drafted opener
- The research brief
- Source links (so the operator can verify any claim)

Operator can: edit, send (one click), skip, or defer. **No message ever sends
automatically.**

**Where the queue lives (v1):** inside the Claude Code session itself — a
simple CLI-style review flow rendered in the chat. Lowest friction match for
the "operator works the queue inside Claude Code each morning" constraint,
keeps all prospect data on the local machine, and avoids shipping drafts
through third-party services (Slack, email) that would create extra privacy
surface area. A local web app may be revisited in v2 if review ergonomics
become a bottleneck.

### 5.5 Reply handling (the conversational agent)
Once a prospect replies, the agent takes over the thread with the goal of
securing a meeting. Hard rules:

- **No instant replies.** The agent waits a humanlike interval before drafting —
  varied, not fixed, typically 20 minutes to a few hours depending on time of
  day and conversation rhythm.
- **Every reply is queued for operator approval.** No exceptions, ever.
- The agent handles objections, answers product questions, qualifies the
  prospect lightly, and steers toward a meeting.

### 5.6 Meeting booking
When the prospect agrees to meet:
1. Agent proposes specific time slots from the operator's Google Calendar availability
2. Prospect picks a slot
3. Agent creates the Google Calendar event with both parties invited
4. Agent sends a confirmation message including the meeting link
5. The thread closes out of the active queue

### 5.7 Silence and re-engagement
- If a prospect goes silent at any stage, a follow-up is auto-drafted for review
  5–7 days later
- Any inbound response — at any stage — immediately hands the thread back to
  the conversational agent

## 6. LLM Cost Model — Operator-in-the-Loop, Pro Subscription Only (v1)

The automation does **not** make autonomous LLM calls. There is no Anthropic
API spend for v1. All LLM work runs through the operator's existing Claude
Pro subscription, used interactively inside Claude Code.

### How it works in practice
- The 10am scheduled job does prospect surfacing only (no LLM)
- The operator opens Claude Code each morning when ready to work the queue
- Claude Code (on Pro) reads the day's prospect list and runs research +
  drafting in an interactive session
- All operator approval, sending, and reply drafting also happens inside
  Claude Code on Pro

### What this means
- **Zero API cost.** The only LLM bill is the existing Claude Pro subscription.
- **The operator must be present each morning** to trigger drafting. This is
  by design — it keeps the operator close to the output, lets the voice be
  tuned quickly, and removes any possibility of overnight or weekend
  surprises.
- **Pro 5-hour usage limits apply.** If the operator hits the limit during a
  heavy session, drafting pauses until reset. The system must handle this
  gracefully (queue prospects for later rather than fail).

### What is forbidden in v1
- No `ANTHROPIC_API_KEY` configured anywhere in the project
- No code path that calls the Anthropic API directly
- No third-party LLM providers (OpenAI, Google, etc.) without explicit
  operator approval and a documented cost cap
- No "background" or "scheduled" LLM calls of any kind

### When this might change
This decision is revisited only if all of the following are true:
1. The voice quality is reliably hitting the bar across 30+ approved messages
2. The operator wants automation of overnight/weekend reply handling
3. A hard monthly API cap is set in the Anthropic Console before any keys
   are added

Any move from operator-in-the-loop to API-backed automation is a deliberate
v2 decision, not a quiet upgrade.

## 7. Voice and Tone Requirements (Critical)

Every message the agent produces — opener, replies, follow-ups — must read as
fully human and conversational. **None of the tells that mark AI-generated text.**

Things the agent must NOT do:
- Em-dash-heavy rhythm
- Tricolon openers ("Quick, simple, effective")
- "I hope this message finds you well"
- Overly polished symmetry
- Buzzword stacking
- Formal sign-offs that sound like a sales template
- Over-explaining or excessive context-setting

Things the agent SHOULD sound like:
- A real founder typing on their phone
- Natural contractions (it's, you're, I'm)
- Occasional sentence fragments
- Small imperfections a human leaves in
- One thought per message, not a wall of text

This voice spec applies to **every** generated message, no matter the stage.

## 8. Constraints and Safety

### LinkedIn account safety
- Operates from the founder's real account
- Daily connection requests stay modest (well below LinkedIn's daily caps)
- All actions are draft-only; sending is human-initiated
- The system should **never** auto-send, auto-connect, or auto-react

### Platform compliance reality
LinkedIn's User Agreement prohibits automated platform interaction. The
human-in-the-loop, one-click-send design is the safety mechanism. The system
must remain a drafting and research tool — not a sender.

## 9. Success Metrics

- **Reply rate** on opening messages (target: above industry baseline of ~5–10%)
- **Meeting book rate** from replied threads (target to be set after first 30 days)
- **Operator time per prospect** — how long it takes to review a draft (target: under 1 minute)
- **Voice fidelity** — qualitative: does the operator change more than 20% of any draft? If yes, the voice spec needs tuning.
- **Account health** — zero LinkedIn warnings or restrictions

## 10. LinkedIn Access Mechanism — Playwright MCP

The system uses **Playwright MCP** (a Model Context Protocol server that
exposes browser automation as tools) to drive LinkedIn through a real browser
session logged into the founder's account. This is the chosen mechanism for:
- Sales Navigator prospect surfacing
- Reading prospect profiles, posts, and comments for the research module
- Surfacing inbound replies into the approval queue
- Sending operator-approved messages (one-click, never auto)

### Why Playwright MCP (and the tradeoffs)
- **Pros:** open-source, well-maintained (Microsoft), works with Claude Code
  and other MCP clients, runs locally (no third-party data middleman),
  transparent about what it's doing
- **Cons:** still constitutes automated platform interaction under LinkedIn's
  TOS; detection risk exists regardless of the tool quality; requires the
  founder's real session to be available to the agent

### Operating principles for Playwright MCP usage
- Browser sessions run **locally on the operator's machine**, not in the cloud
- Authentication uses the operator's existing browser session — no credentials
  passed to the agent
- The agent is restricted to a defined set of allowed actions (read profile,
  read inbox, draft message, send specific approved message). It is **not**
  given a general "do anything in the browser" mandate.
- All sending actions require operator confirmation in the approval queue
- Action volume is rate-limited at the tool layer (e.g., max N profile views
  per hour, max M connection requests per day), independent of what the LLM
  decides to do
- Session activity is logged so any anomalous behavior is auditable

## 11. Data Protection and Privacy

Prospect data is **personal data of third parties** under most privacy regimes
(Malaysia PDPA, Singapore PDPA, GDPR for any EU-based prospects). The system
must be designed with that in mind from day one.

### Lawful basis and minimization
- Only collect data necessary for the outreach decision (no broad scraping)
- Store only what's needed for the active outreach lifecycle — not indefinitely
- Don't aggregate or resell prospect data; it stays inside this system

### Storage and security
- All prospect data, drafts, threads, and research stored locally or in a
  single private database under the operator's control
- Database encrypted at rest; backups encrypted
- No prospect data sent to third-party services beyond the LLM provider used
  for drafting (and that data is not used for model training — confirm with
  provider settings)
- API keys, session tokens, and credentials kept in a `.env` file, never
  committed to git, never logged

### Retention
- Active prospects (in the funnel): retained as long as the thread is open
- Closed-out prospects (meeting booked, declined, or gone silent past 90 days):
  research data and message drafts deleted; only minimal record kept for
  duplicate-prevention
- Operator can request full deletion of any prospect's record at any time

### Right to be forgotten
- If a prospect explicitly asks not to be contacted, the system marks them as
  do-not-contact permanently and deletes their research data
- A documented manual process exists for handling deletion requests

### LLM privacy
- The LLM provider used for research and drafting must have a clear data-use
  policy — prospect content sent to the model must not be retained for training
- Where possible, anonymize or minimize what's sent to the LLM (e.g., send
  summarized post content rather than identifying metadata)
- Document which LLM provider is used and link to their data policy in the repo

## 12. Out of Scope (v1)
- Email outreach
- Other social channels (X, Instagram, etc.)
- Multi-operator / team features
- A built-in CRM
- Auto-sending of any kind
- Analytics dashboards beyond basic counts
- Cloud-hosted browser sessions (local-only in v1 for security and TOS reasons)

## 13. Open Questions
- [ ] ~~Which LLM provider for research/drafting?~~ → **Resolved:** Claude via Pro subscription, used interactively in Claude Code. No API in v1.
- [ ] ~~Where does the approval queue live?~~ → **Resolved:** CLI-style review flow inside the Claude Code session for v1. Local-only, zero extra services. Revisit a local web app in v2 if ergonomics justify it.
- [ ] Backup plan if the LinkedIn account is restricted
- [ ] How is the founder's "voice" captured initially — sample messages, interview, fine-tuning?
- [ ] What database is used for local storage, and is encryption-at-rest configured by default?
- [ ] Concrete daily/hourly rate limits at the Playwright MCP layer (numbers to be set conservatively before first run)
