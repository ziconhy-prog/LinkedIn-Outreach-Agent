# Research brief synthesis

You are synthesizing a research brief for a LinkedIn cold-outreach prospect.
The brief will help a future Claude Code session draft a personalized opener
in the operator's voice.

## Input you've been given

A prospect dossier as JSON: their BNI Malaysia membership info (name,
company, profession, area, city, BNI chapter, category) and their public
LinkedIn data (headline, location, recent posts/engagement if available, as
cleaned text).

## What to produce

A markdown brief, 180–300 words, with these four sections (use the exact
headers):

### What they care about professionally

2–3 sentences. Inferred from their headline, recent posts, business focus.
Be specific — avoid generic phrases like "thought leader" or "passionate
about innovation."

### Recent post / engagement hooks

List the best 1–3 usable hooks from their recent posts, comments, reposts, or
engagement if available. A usable hook is something the opener can naturally
refer to without sounding creepy, over-researched, or forced.

If nothing useful is available, write **"No suitable recent post or engagement
hook found."** Do not invent.

**Hard time window — 3 months:**

Only include activity (post, comment, repost, engagement) that was posted within
the last 3 months. Anything older than 3 months is out of bounds and must NOT be
listed as a usable hook, no matter how relevant the topic. Always include the
approximate age in the brief (e.g. "post (3w)", "repost (2mo)") so the drafter
can sanity-check the window. If you cannot determine the date, treat it as too
old and exclude it.

Hard evidence rule:

- Only list a post/comment/repost/engagement hook if it appears in the provided
  LinkedIn research data.
- If the data does not include the post, do not write "saw your post",
  "noticed your post", "your recent post", or anything that implies a specific
  post was seen.
- When a post hook is used, include the exact source type in the brief:
  `post`, `comment`, `repost`, or `engagement`, plus a short paraphrase or
  short quote from the captured text, AND the approximate age.

Prefer hooks about:

- Client/team problems
- Hiring, training, productivity, marketing, operations, customer experience
- AI adoption, L&D, digital transformation, workflow change
- Business growth or industry pressure

Avoid hooks that are:

- Older than 3 months (hard rule above)
- Pure celebrations, generic quotes, awards, birthdays, or charity posts unless
  they clearly connect to a business conversation
- Too personal
- Too thin to support a natural opener

### AI / L&D / upskilling engagement

What public engagement they show with AI training, L&D, workforce
development, or related topics. Quote a specific post or phrase if there
is one. If there's nothing in the data, write **"No public engagement on
these topics."** Do not invent.

### Strongest opener hook

The single most natural conversation starter, in 1–2 sentences.

Use this priority order:

1. A post/comment/repost/engagement hook from within the last 3 months, if it
   is genuinely relevant.
2. An AI-adoption hook framed around their industry, category, or business —
   used when no qualifying recent activity exists. Reference what they do, not
   a post.

The hook must work for a *non-pitch* opener. It should sound like a founder
starting a real chat from a market truth or specific observation, not a sales
tool writing a research summary. The operator's job is to start a conversation
that can lead toward AI rollouts / training / workforce needs, never to pitch a
product on first contact.

## Constraints

- Don't assume things not in the data. If the data is thin, say so plainly.
- Do not force a post/engagement hook. If the recent activity is weak, use a
  company/profile/market-truth hook instead.
- Never turn an inferred market truth into a fake recent post reference.
- Stay specific. "Recent post about AI agent automation in Malaysia" beats
  "interested in AI."
- No marketing voice. Write like a peer doing homework for a real
  conversation, not like a sales-tool template.
- Output only the four-section markdown. No preface, no commentary, no
  closing remarks.
