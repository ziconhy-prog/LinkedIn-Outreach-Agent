# LinkedIn Outreach Automation — PRD

**Status:** Draft
**Last updated:** 2026-05-07
**Version:** 0.2

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
- Surface 10 high-fit prospects per workday, ranked by buying signal strength
- Produce a research brief per prospect that the founder would have written themselves
- Draft opening messages that are indistinguishable from the founder's own writing
- Handle reply conversations end-to-end (drafting only) until a meeting is booked
- Block the meeting on the founder's Google Calendar once the prospect agrees on a time
- Keep the founder's LinkedIn account safe — modest volume, human approval, real account

### Non-Goals
- No fully automated sending. Every message is approved by the operator via Telegram.
- No mass outreach. Quality over volume — daily caps stay modest.
- No multi-user / team features in v1. Single operator.
- No CRM replacement. This system feeds outreach; pipeline lives elsewhere if needed.
- No paid ad targeting, no email outreach, no other channels in v1.

## 4. Target Users

### Operator (the user of this system)
The founder running outreach. Approves every message via Telegram, edits when
needed, handles escalations the agent flags.

### Prospects (the audience being reached out to)

Primary v1 target is the **BNI Malaysia member network** — small business
owners and professionals in IT/software, training, marketing, and HR
consultancy categories, mostly in Malaysia and SEA. They are end-buyers for
AI training (small teams of their own to upskill) and occasionally adjacent
fits (would refer/resell to their own clients).

**Approach:** ease them into AI/L&D conversation. Do not mention or pitch
SkillTrainer AI on first contact. Do not mention BNI or reveal that the
prospect came from a source list in the opener. The first message should feel
like a soft peer-to-peer note, not a campaign touch.

Opening tone should be hook-led, relaxed, and engaging. The agent should avoid
formal discovery-call language and boring interview questions. A good opener
starts with a relatable pattern or tension from the prospect's world, then asks
one easy-to-answer question. It should feel like a real person starting a chat,
not a consultant running a questionnaire.

Before drafting, the agent should research the prospect's visible recent posts,
comments, reposts, and engagement where available. If a suitable recent
activity hook exists, the opener should use it lightly. Suitable hooks are
business-relevant: client/team problems, productivity, hiring, training,
marketing pressure, operations, customer experience, AI adoption, or workflow
change. If recent activity is missing, generic, too personal, or not useful,
the opener falls back to profile/company/category context, then to a
role-specific market-truth hook.

The agent must never fabricate activity. It may only say "saw your post",
"noticed your post", "your recent post", or reference a specific
comment/repost if Playwright research captured that exact activity. If no
related activity is available, the opener must not imply any post was seen.

The commercial goal is to secure a face-to-face meeting with a potential
paying client and introduce SkillTrainer AI into their workforce context.
Product introduction should still happen gradually. Replies 1–2 stay curious
and open-ended, but should qualify business need, team context, AI adoption
friction, training gaps, or urgency through natural follow-ups, small reactions,
and casual opinion prompts. Around replies 3–4, if the prospect shows
relevant interest or pain around AI adoption, training, team readiness, or
implementation friction, the agent may briefly introduce SkillTrainer AI as a
practical AI training platform and steer toward a face-to-face meeting.

A small "signal" stream of LinkedIn users discovered through hashtag pages
(`#MalaysiaAI`, `#LearningAndDevelopment`, etc.) supplements the BNI list.
These tend to be people publicly engaging with AI/L&D topics in the region.

### Prospect-fit validation

Before researching or drafting for a candidate, the system must validate that
the LinkedIn profile likely matches the BNI row:

- Search LinkedIn by name first.
- Inspect the result list for current company, headline, and location match.
- Confirm the prospect is Malaysia/SEA-based or clearly tied to the BNI
  Malaysia row.
- Reject profiles outside Malaysia/SEA unless the BNI row clearly proves they
  operate in the target geography.
- Deprioritize AI-provider companies, AI automation agencies, AI chatbot
  vendors, AI training providers, and other businesses that sound like direct
  competitors or implementation partners.
- Prioritize non-AI companies with teams or client-facing operations that could
  benefit from practical workforce AI training, such as marketing/creative
  agencies, HR consultancies, training companies, professional services,
  retail/service businesses, and conventional SMEs.
- If the match is uncertain, skip and pick another prospect. Do not draft.
- For dry runs, stop searching once the requested number of valid prospects has
  been selected.

## 5. Core Workflow

**Trigger:** the operator sends a command to a private Telegram bot to start
the day's run. Telegram is the operator's interface while away from the desk;
the Playwright session, research, and drafting all run locally on the
operator's Mac and report back through the bot.

### 5.1 Daily prospect surfacing

The bot surfaces 10 candidates per day from two sources.

**Source A — BNI Malaysia member list (primary).** A static PDF the operator
provides is parsed once into a structured local list. Each row has name,
company, profession, area, city, BNI chapter, phone, and category. The list
contains ~700 entries across IT/software, training, marketing, and HR
consultancy categories. No row has a LinkedIn URL — the system enriches on
demand.

**Source B — hashtag-driven discovery (signal layer).** A short list of
LinkedIn hashtags relevant to the operator's audience. Default set:
`#MalaysiaAI`, `#LearningAndDevelopment`, `#Upskilling`, `#HRMalaysia`,
`#FutureOfWork`, `#AI`, `#AIMalaysia`, `#HRDC`. The system reads recent
posters under each hashtag, filters to Malaysia/SEA, and surfaces fresh names
not already in the queue. The hashtag list lives in `hashtags.txt` at repo
root and is operator-editable.

**Daily flow (10:00 AM Malaysia time, UTC+8):**
1. Pick ~15 candidates from Source A (next un-enriched BNI rows) and ~5 from Source B
2. For each, search LinkedIn via Playwright by name, then validate visible
   result-list company/headline/location before capturing a profile URL
3. Score on cheap signals (recent post about AI/L&D, recent job change, category match)
4. Pick top 10 by score, write to local queue
5. Telegram message: **"Today's queue is ready: 10 prospects. Reply /research to start drafting openers."**

The 10am surfacing job does **only this**. No LLM calls.

### 5.2 Per-prospect research

When the operator sends `/research` from Telegram, Claude Code — running
interactively in the operator's open Pro session on the Mac — pulls per
prospect:

- Last 10 LinkedIn posts and comments
- Visible company info
- Public mutual connections, if any

It produces a structured brief per prospect: what they care about
professionally, any AI/L&D/upskilling engagement, the strongest opener hook.

Research runs during the operator's morning window when Claude Code is open —
not in the background.

### 5.3 Opener drafting

For each researched prospect, the operator sends `/draft`. Claude Code
generates an opener using:

- The voice samples in `voice-samples/` (20 files) — read every time
- The negative-pattern list (no em-dashes, no "I hope this finds you well", no formal sign-offs, etc.)
- **Persona angle:** BNI members are small business owners in
  IT/training/marketing/HR. Ease them into AI/L&D conversation. **Do NOT
  pitch SkillTrainer AI on first contact.** Talk about AI rollouts, training
  challenges, workforce readiness — let curiosity drive the next message.

Closes with a low-friction ask — a question, a reaction prompt — never a hard pitch.

### 5.4 Approval queue (Telegram)

Each draft pushes to the operator's private Telegram chat as:

> **[Prospect Name]** — *Title, Company*
> 🔗 [profile URL]
> 📋 [research brief, 3 lines]
>
> 💬 **Drafted opener:**
> *[message text]*
>
> [✅ Approve & Send] [✏️ Edit] [⏭ Skip] [⏰ Defer]

Tapping **Approve & Send** triggers Playwright to send that exact message.
**No message sends without an operator tap.** Editing opens a text input in
Telegram for inline corrections before send.

### 5.5 Reply handling

When a prospect replies on LinkedIn, the bot detects it (Playwright polls the
inbox at jittered intervals during Malaysia business hours), pulls the new
message, and **waits a humanlike interval — varied, typically 20 minutes to a
few hours, respecting Malaysia business hours UTC+8** — before drafting.

Once the delay elapses, Claude Code drafts a reply (only when the operator's
Pro session is open). The draft pushes to Telegram with the same Approve /
Edit / Skip / Defer buttons.

**Escalation rule:** if the prospect asks about pricing, contract terms, data
privacy, security, or any topic the agent can't answer with confidence, the
bot does **not** draft. It pushes the message flagged ⚠️ NEEDS YOU and waits
for the operator to handle directly.

**Never promise pricing.** Even when the agent has seen a price hinted at
in voice samples, research data, or anywhere else, it must NEVER state a
price, a range, or a "starting from" figure on the operator's behalf.
Pricing is always a ⚠️ NEEDS YOU escalation, full stop. Same applies to
contract terms, refund policy, SLAs, and any other commercial commitments.

### 5.6 Meeting booking (Google Calendar)

When the prospect agrees to meet and suggests a time, the bot:

1. Checks the operator's Google Calendar free/busy for the suggested time
   (standard business-hour buffer applied).
2. If **free**: drafts a confirmation reply ("Tuesday 3pm works — speak then"),
   pushes to Telegram for operator approval. On approval, sends the LinkedIn
   confirmation **and** creates a Google Calendar event on the operator's
   calendar only — block-only, **no email invite to the prospect.** Event
   title: `LinkedIn meeting — [Prospect Name] (re: [short hook])`. Event
   description includes the LinkedIn thread URL.
3. If **busy**: drafts a near-alternative reply ("That window's taken — would
   Wednesday 4pm work?"), pushes to Telegram for operator approval. Loops
   until time is agreed.

The bot does **not** proactively propose slots; it waits for the prospect to
suggest. The bot does **not** invite the prospect via email — operator
handles any formal meeting link separately.

After event creation, bot pushes Telegram notification:

> 🎯 **Meeting booked — [Prospect Name]**
> 📅 [day/time]
> 📍 Calendar event created on your Google Calendar
> 💬 Thread: [link]

Thread is then closed in the active queue.

**Setup prerequisite:** operator must complete Google Calendar OAuth before
first booking. Setup flow handled in a separate one-time command
(`/connect-calendar`).

### 5.7 Silence and stop rules

- **Never two outbound messages in the same calendar day to a non-responding
  prospect.** If the operator's last outbound has not received a reply, the
  bot must NOT queue another outbound to that prospect on the same day. The
  1-day follow-up gap below applies for the next attempt. This rule does NOT
  apply when the prospect has actively replied — back-and-forth conversations
  can continue same-day, subject to the humanlike delay in §5.5.
- **Two outbound messages with no reply → close thread.** Opener + 1
  follow-up. Follow-up is drafted **1 day after the opener** and queued for
  operator approval like any other draft. If still no reply 1 day after the
  follow-up, bot closes the thread automatically and logs "ghosted." No
  further outreach to that prospect.
- **Polite "no thanks" →** bot drafts a "no worries, take care" closer for
  operator approval, then closes the thread.
- **Aggressive negative or do-not-contact request →** bot does NOT draft.
  Pushes flagged ⚠️ NEEDS YOU and adds the prospect to the permanent
  do-not-contact list. Operator handles directly.
- **Inbound message after a thread was closed →** re-opens the thread
  immediately, drafts a reply per §5.5.

### 5.8 Daily report (5:00 PM Malaysia time, UTC+8)

At 5pm each workday the bot pushes one Telegram summary:

```
📊 Daily Report — [date]
• Sent today: X openers, Y replies (Z needs you)
• New replies received: N
• Threads closed: A ghosted, B declined, C meeting booked
• Active threads: M
• Tomorrow's queue: ready (10 prospects) / not yet
• Follow-up notes: [1–2 sentence reflection from the agent
  on what's working / not, drawn from the day's threads]
```

## 6. LLM Cost Model — Operator-in-the-Loop, Pro Subscription Only (v1)

The automation does **not** make autonomous LLM calls. There is no Anthropic
API spend for v1. All LLM work runs through the operator's existing Claude
Pro subscription, used interactively inside Claude Code.

### How it works in practice
- The 10am scheduled job does prospect surfacing only (no LLM)
- The operator works the queue from Telegram throughout the day; Claude Code
  on the Mac handles research and drafting interactively when the operator
  triggers commands
- Claude Code (on Pro) reads the day's prospect list and runs research +
  drafting in an interactive session
- All operator approval, sending, and reply drafting are gated by Telegram
  taps, with the underlying drafting work done in Claude Code on Pro
- Background reply detection (Playwright polling) runs without LLM calls.
  Drafting happens only when the operator's Pro session is open and a
  /draft or reply is triggered.

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

**Voice samples:** the writing module reads `voice-samples/` (20 RTF files in
v1) on every draft. These are the ground truth for the operator's voice; the
rules below are the negative-pattern guardrails on top of that.

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
- The system should **never** auto-send, auto-connect, or auto-react. Every
  send is gated behind an explicit operator tap in Telegram.

### Platform compliance reality
LinkedIn's User Agreement prohibits automated platform interaction. The
human-in-the-loop, one-click-send design is the safety mechanism. The system
must remain a drafting and research tool — not a sender.

The Telegram approval gate is the structural enforcement of the
human-in-the-loop rule. The Playwright "send message" tool must require a
Telegram-approved queue-entry ID and must reject raw message text from any
other source.

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
- Reading prospect profiles, posts, and comments for the research module
- Searching LinkedIn by name to enrich BNI rows with profile URLs
- Surfacing inbound replies into the approval queue
- Sending operator-approved messages (one tap, never auto)

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
- **In v1 the allowed list is:** read profile, read posts, read comments,
  read inbox, search LinkedIn for a name, send a queue-approved message,
  send a queue-approved connection request. Generic browser tools
  (`browser_evaluate`, `browser_run_code_unsafe`) must NOT be exposed to the
  writing/reply path.
- All sending actions require operator confirmation in the Telegram approval queue
- Action volume is rate-limited at the tool layer (e.g., max N profile views
  per hour, max M connection requests per day), independent of what the LLM
  decides to do. **LinkedIn searches for URL enrichment count toward the
  daily profile-view budget (each name search = 2 page views budgeted).**
- Session activity is logged so any anomalous behavior is auditable

## 11. Telegram Interface

The operator interacts with the system entirely through a private Telegram
bot during the workday. The bot is the queue UI, the alert channel, and the
daily-report channel.

### 11.1 Bot setup

- Bot is created in BotFather, token stored in `.env` as `TELEGRAM_BOT_TOKEN` (never committed).
- Operator's Telegram user ID is stored in `.env` as `TELEGRAM_OPERATOR_USER_ID`.
  The bot rejects every message from any other user ID, full stop. There is
  no "team" mode.
- Bot runs as a long-lived process on the operator's Mac. Mac must be awake
  during business hours for the bot to respond.

### 11.2 Operator commands

- `/start` — health check; bot replies with system status (queue size, active threads, last poll time)
- `/queue` — show today's surfaced prospect list
- `/research` — kick off the per-prospect research pass (interactive in Claude Code)
- `/draft` — draft openers for researched prospects
- `/pause` — pause the bot from sending or polling (e.g., if LinkedIn shows a warning)
- `/resume` — resume after pause
- `/connect-calendar` — one-time Google Calendar OAuth flow
- `/report` — push the daily report on demand (in addition to 5pm auto-push)

### 11.3 Inline button behavior

Every draft message in Telegram has four buttons: `✅ Approve & Send`,
`✏️ Edit`, `⏭ Skip`, `⏰ Defer`.

- **Approve & Send:** invokes the Playwright send action with the queue-entry ID. Returns confirmation when sent.
- **Edit:** prompts the operator to type a replacement; bot replaces the draft and re-shows the buttons.
- **Skip:** marks this draft as skipped (no send), thread state preserved.
- **Defer:** re-queues for review later in the day; bot will re-push at next polling tick.

### 11.4 Escalation flag

When the agent encounters something outside its authority (pricing,
contracts, data/privacy, security, anything ambiguous), the message pushes to
Telegram with a ⚠️ NEEDS YOU header. No draft is generated. The operator's
reply (typed in Telegram) becomes the message sent to the prospect after the
operator confirms with another approve tap.

## 12. Data Protection and Privacy

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
- Database is plain SQLite. Encryption at rest is provided by macOS
  FileVault (full-disk encryption — operator has confirmed it is enabled).
  Backups, if made, must be stored on encrypted media.
- No prospect data sent to third-party services beyond the LLM provider used
  for drafting (and that data is not used for model training — confirm with
  provider settings)
- API keys, session tokens, and credentials kept in a `.env` file, never
  committed to git, never logged
- Telegram bot token, Google Calendar OAuth tokens, and the Playwright session
  path are stored in `.env`. Never logged, never shared, never committed.

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

## 13. Out of Scope (v1)
- Email outreach
- Other social channels (X, Instagram, etc.)
- Multi-operator / team features
- A built-in CRM
- Auto-sending of any kind
- Sending Google Calendar invites to the prospect (block-only on operator's calendar in v1)
- Analytics dashboards beyond basic counts
- Cloud-hosted browser sessions (local-only in v1 for security and TOS reasons)

## 14. Open Questions
- ✅ ~~Which LLM provider for research/drafting?~~ → **Resolved:** Claude Pro via Claude Code on operator's Mac. No API in v1.
- ✅ ~~Where does the approval queue live?~~ → **Resolved:** private Telegram bot with inline approve/edit/skip/defer buttons (Path A).
- ✅ ~~Founder voice baseline?~~ → **Resolved:** 20 RTF samples in `voice-samples/`. May refresh as voice tunes.
- ✅ ~~Sales Nav access?~~ → **Resolved:** not used. BNI list + hashtag stream replace it.
- [ ] Backup plan if the LinkedIn account is restricted
- ✅ ~~Local database choice and encryption-at-rest configuration?~~ → **Resolved:** plain SQLite (built into Python). Encryption-at-rest provided by macOS FileVault (operator confirmed enabled).
- [ ] Concrete daily/hourly Playwright rate limits (suggested starting numbers in §10; tune before first live run)
- [ ] Hashtag list refinement after first 30 days of data
- [ ] Voice fidelity threshold for graduating from Path A toward more autonomy (post-v1 question)
