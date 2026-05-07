# Tools and Setup Guide

This is your "what do I need to install and sign up for" cheat sheet. You don't
need to do all of this on day one — work through it in order and stop when
you've got what you need for the current step.

## How LinkedIn access actually works in this project

You're using **Playwright MCP** to drive LinkedIn. Quick plain-English version
of what that means:

- **Playwright** is an open-source browser automation library made by
  Microsoft. It lets software drive a real browser the same way you do —
  clicking, scrolling, typing.
- **MCP** (Model Context Protocol) is the standard way Claude connects to
  external tools. An "MCP server" is a small program that exposes a set of
  tools to Claude.
- **Playwright MCP** is the bridge: it gives Claude controlled access to a
  real browser session, with each action exposed as a discrete tool Claude
  can call.

For your project, this means: you log into LinkedIn once on your machine in a
browser Playwright manages, and from then on Claude can read profiles, surface
inbox messages into the approval queue, and (after you click approve) send
specific messages.

### Why this approach over alternatives
- **vs. third-party data services (Apollo, Clay, Phantombuster):** runs
  locally, no third-party middleman gets your prospects' data, no extra
  monthly cost
- **vs. raw Playwright code:** Claude can use it directly through a clean
  tool interface; no need for you to learn Playwright's API
- **vs. doing nothing automated:** unlocks the daily research and queueing
  the whole project depends on

### What Playwright MCP does NOT solve
- **TOS risk.** LinkedIn's User Agreement still prohibits automated platform
  interaction, regardless of which tool drives the browser. The operational
  rules in your CLAUDE.md (modest volume, human approval, real account, local
  session) are how you manage that risk; the tool itself doesn't make the
  risk disappear.
- **Detection.** LinkedIn's bot detection looks at behavior, not just
  technology. Random-feeling pacing, conservative volume, and a real session
  from a real device are what reduce detection — not the choice of automation
  library.

### Privacy implications you should be aware of
Once your agent has a browser session, it can see prospect profiles, your
inbox, mutual connections — anything you can see when logged in. This is
**third-party personal data**, and depending on where your prospects are
based, you have real obligations:

- **Malaysia (PDPA):** prospects in Malaysia are covered by the Personal
  Data Protection Act
- **Singapore (PDPA):** prospects in Singapore by their PDPA
- **EU/UK (GDPR):** any EU/UK-based prospects trigger GDPR
- **General good practice:** minimize what you store, encrypt it, delete it
  when no longer needed, honor do-not-contact requests immediately

Your CLAUDE.md and PRD now bake these requirements in. Claude Code will
follow them when it builds the system, but it's worth knowing why they're
there.

## Tools you'll need (in order of when you'll need them)

### Phase 1 — Just getting Claude Code running in your IDE

**1. An IDE**
Pick one. Both are fine for your level:
- **VS Code** — free, the most common choice, lots of help available online
- **Antigravity** — Google's newer IDE; more agent-first but rougher around the edges

If you have no preference, start with VS Code. It's the safer default.

**2. Claude Code**
Install per the setup steps from earlier in our conversation. You'll need a
paid Claude plan (Pro, Max, or API credits).

**3. The Claude Code extension for your IDE**
- VS Code: search "Claude Code" in the Extensions panel
- Antigravity: same, search "Claude Code" in Extensions

**4. A project folder**
Make a regular folder on your computer — call it whatever you want, e.g.,
`linkedin-outreach`. Put the three files I'm giving you (`PRD.md`,
`CLAUDE.md`, this file) inside it. Open that folder in your IDE.

### Phase 2 — Before any code gets written

**5. A Google account with Calendar access**
The one whose calendar will hold the booked meetings. You'll later create
something called a "Google Cloud project" to give the automation permission to
read/write your calendar. Claude Code will walk you through this when you get
there — don't worry about it yet.

**6. Your Claude Pro subscription (you already have this)**
For v1, all LLM work in this project runs on your existing Claude Pro
subscription, used inside Claude Code. **You do not need an Anthropic API key,
and you should not buy API credits.** If anything in the project ever asks you
to add an API key, that's a signal something is being built differently from
how the PRD specifies — push back.

This means you don't pay anything beyond Pro. The tradeoff is that you have
to be present to work the queue each morning (more on this in the daily
routine section below).

**7. LinkedIn Sales Navigator subscription**
You almost certainly already have this if you're doing serious outreach. If
not, the cheapest tier is fine for now. This is where prospect sourcing comes
from.

**8. A folder of your own past messages**
This is the most important non-software thing on the list. Collect 20+ real
messages you've written — DMs, openers, replies — and save them as plain text
in a folder called `voice-samples/` inside your project. The writing module
will use these to learn your voice. Without this, generated messages will
sound like generic AI output no matter how good the prompt is.

### Phase 3 — Installing Playwright MCP

When Claude Code is set up and your project folder is open, you'll add
Playwright MCP as a connected tool. The exact steps will be guided by Claude
Code itself — that's the point of MCP servers: Claude knows how to install
and configure them.

What will happen, in plain English:

1. **You'll install the Playwright MCP server.** This is a one-time install,
   handled via a single command Claude Code runs for you (it uses Node.js
   under the hood). Claude Code will tell you what to type.

2. **You'll register it as an MCP server in Claude Code's config.** This
   tells Claude "you have access to a browser-driving tool now." Again,
   Claude Code walks you through this — it's an edit to a config file.

3. **You'll open a browser window through Playwright and log into LinkedIn
   once, manually.** Your password and 2FA never go through Claude. The
   session is then saved locally so the agent can use it on subsequent runs.
   This step is **important** — Claude must never see your LinkedIn
   credentials, only the resulting session.

4. **You'll set rate limits.** Conservative numbers are baked into your
   CLAUDE.md. Claude Code will implement them at the tool layer before
   anything goes live.

5. **You'll do a dry run.** Before any messages are sent, you'll do an
   end-to-end test against a small handful of prospects, with sending
   disabled, to confirm the research and drafting quality.

The first time you ask Claude Code to "set up Playwright MCP per the project
rules in CLAUDE.md," it will read those rules and walk you through each
step.

### A safety habit to build now

Even with all the constraints in place, get into the habit of:
- Running the system only when you can review the queue same-day
- Watching the LinkedIn account for any warning emails or in-app notices
- Pausing immediately if you see anything unusual (a captcha, a "we noticed
  unusual activity" message, etc.)
- Keeping your daily volume well below the limits in your CLAUDE.md, especially
  for the first 30 days while you're tuning

## Your daily routine (once everything is built)

Because v1 runs entirely on your Pro subscription with no API automation,
your day-to-day flow looks like this:

**Around 10:00 AM Malaysia time** — the scheduled job runs in the background.
It opens Playwright, surfaces 10–20 prospects from Sales Navigator, scores
them, and writes them to the local queue. It does **not** generate any
research or drafts — that part needs you.

**Whenever you sit down to work the queue** (could be 10:05 AM, could be
after lunch — your call) — you open your IDE, open Claude Code, and tell it:

> Read today's prospect queue. For the top 10 prospects, run the research
> pass and draft openers per the rules in CLAUDE.md. Show them to me one
> by one so I can review.

Claude Code, running on your Pro subscription, does the research and
drafting interactively. You review, edit, and approve. Approved messages go
into the send queue. You click send when ready.

**For replies during the day** — when a prospect responds, the system queues
the reply. Next time you open Claude Code, ask it to draft replies for any
new responses, with the humanlike delay built into the timestamping. You
review and approve as before.

**A note on Pro usage limits:** Claude Pro has rolling 5-hour usage caps. A
heavy session of 10–20 prospects with deep research could occasionally hit
that limit. If it does, Claude Code will tell you when limits reset. Just
come back later. No workarounds, no API fallback — that's a v2 conversation.

## Why this approach (briefly)

You explicitly said you don't want extra spend on the Anthropic API. Locking
the system to "operator-in-the-loop, Pro only" delivers that. It also has a
side benefit: you stay close to the output during the first 30 days when
voice tuning matters most. Once you've approved 30+ messages and trust the
voice, we can revisit whether limited API use makes sense for v2.



1. Make a folder on your computer for this project
2. Save `PRD.md`, `CLAUDE.md`, and this guide into it
3. Install your IDE if you haven't already
4. Install Claude Code and the IDE extension
5. Open the project folder in your IDE
6. Start a Claude Code session and say: "Read the PRD and CLAUDE.md, then ask
   me the open questions you need answered before we start building. After
   that, walk me through setting up Playwright MCP per the project rules."

Claude Code will read both files automatically and ask you the right
follow-up questions in order. You won't need to remember any of this — the
files do the remembering for you.
