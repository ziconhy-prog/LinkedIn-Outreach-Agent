"""Draft LinkedIn replies using the Claude API.

Follows the 4-stage conversation arc defined in files/CLAUDE.md:
  Stage 2 — broaden to their industry, stay curious
  Stage 3 — surface the AI adoption angle
  Stage 4 — introduce SkillTrainer AI, move toward a meeting

The system prompt and research brief are cache-controlled so repeated
calls within the same conversation stay cheap.
"""

from __future__ import annotations

from pathlib import Path

import anthropic

from outreach.config import ANTHROPIC_API_KEY, PROJECT_ROOT


def _load_humanize_rules() -> str:
    """Load voice rules from the humanize folder at project root."""
    skill = PROJECT_ROOT / "humanize" / "SKILL.md"
    patterns = PROJECT_ROOT / "humanize" / "overused-ai-patterns.md"
    parts = []
    for path in (skill, patterns):
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n\n---\n\n".join(parts) if parts else ""


_HUMANIZE_RULES = _load_humanize_rules()
_VOICE_SPEC = (PROJECT_ROOT / "prompts" / "voice.md").read_text(encoding="utf-8")


_STAGE_INSTRUCTIONS: dict[int, str] = {
    2: (
        "React to their reply with genuine agreement. Don't position yourself as having "
        "all the answers. Ask about their business context: what growth looks like right "
        "now, what the team is dealing with. Stay curious. Do not mention SkillTrainer AI. "
        "One question at the end, easy to answer in two sentences."
    ),
    3: (
        "Connect their specific struggle to the broader pattern: knowledge and judgment "
        "stuck in the heads of a few senior people, AI tools landing on top without fixing "
        "the underlying gap. Agree that most growing teams face this. Ask if they're seeing "
        "the same thing. Do not introduce SkillTrainer AI yet. One question."
    ),
    4: (
        "Introduce SkillTrainer AI now, tied directly to the pain they named in their own words. "
        "Frame it as something that helped teams in a similar spot, not a cure-all. "
        "One sentence on what it does. Then make a meeting ask based on their location:\n"
        "- If the prospect is in KL or Selangor (Petaling Jaya, Subang, Puchong, Klang, "
        "Shah Alam, Cheras, Ampang, Bangsar, KLCC, Damansara, or anywhere in the Klang Valley): "
        "invite them for coffee in KL. Keep it casual — 'grab a coffee in KL', 'meet up in KL'. "
        "Do not say 'face-to-face meeting' or anything formal.\n"
        "- If the prospect is outside KL/Selangor (Penang, Johor, Sabah, Sarawak, Singapore, "
        "or anywhere else): ask if they'd be open to a quick video call instead. "
        "Keep it low pressure — 'happy to jump on a quick call if that's easier'.\n"
        "- If location is unknown: default to asking if they'd prefer a coffee or a call.\n"
        "Do not ask for a meeting AND ask a question in the same message."
    ),
}

_REPLY_RULES = """\
REPLY FORMAT
- One question per message. Never two. Never zero unless making a meeting ask.
- Do not pitch SkillTrainer AI unless this is Stage 4.

VARY HOW YOU OPEN EACH MESSAGE
Never start two messages in a row the same way. Mix it up naturally:
- Jump straight into the thought: "Most teams hit that wall..."
- Light reaction then move on: "That makes sense." and continue.
- Ask first: "Is it more the senior guys being stretched, or..."
- Use "I wonder if..." or "worth considering" when genuinely unsure.
- Use "fair point" or "that's a good call" sparingly — once per conversation max.

ALLOWED ACKNOWLEDGMENT — pick ONE, keep it tiny:
- "Makes sense."
- "Fair."
- "Yeah."
- "Got it."
- "Hear that a lot."
Then IMMEDIATELY move to a question or a short remark from YOUR world.
No explanation, no insight, no rephrasing in between.

STRUCTURE FOR EVERY STAGE 2 AND STAGE 3 REPLY:
  [3-7 word acknowledgment.] [Your question or a personal note.]
That's it. Two short sentences max. If you have more to say — don't.\
"""


def _conversation_stage(outbound_count: int) -> int:
    """Derive conversation stage from how many outbound messages have been sent.

    The opener counts as outbound #1, so the first reply is stage 2. Clamped
    to 2..4 — stage 1 has no reply instructions (it's the opener), and without
    the lower clamp a thread with outbound_count=0 would fall through to the
    stage-4 'ask for a meeting' instructions on the very first reply.
    """
    return min(max(outbound_count + 1, 2), 4)


def draft_reply(
    prospect: dict,
    research_brief: str,
    conversation_history: list[dict],
    outbound_count: int,
) -> str:
    """Draft a reply using Claude API. Returns plain message text.

    Args:
        prospect: DB row dict with at least name, company, category.
        research_brief: Markdown brief synthesised from LinkedIn research.
        conversation_history: List of message dicts ordered oldest-first,
            each with keys: direction ('inbound'/'outbound'), content (str).
        outbound_count: How many outbound messages Zico has sent so far
            in this thread (used to determine stage).
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set in .env. "
            "Add it to enable automated reply drafting."
        )

    stage = _conversation_stage(outbound_count)
    stage_instruction = _STAGE_INSTRUCTIONS.get(stage, _STAGE_INSTRUCTIONS[4])

    system_text = f"""\
You are drafting a LinkedIn reply on behalf of Zico, founder of SkillTrainer AI —
a practical AI workforce training platform for Malaysian SMEs and growing ops teams.

{_VOICE_SPEC}

{_HUMANIZE_RULES}

{_REPLY_RULES}

Research on this prospect:
Name: {prospect.get('name', '')}
Company: {prospect.get('company', '')}
Category: {prospect.get('category', '')}
Location: {prospect.get('location') or prospect.get('city') or prospect.get('area') or 'Unknown'}

Brief:
{research_brief or '(No research brief available — use profile/company context only.)'}

Current conversation stage: {stage} of 4
Stage instruction: {stage_instruction}

Write only the reply message text. No preamble, no explanation, no quotes.
Do not start with "Hi" or the prospect's name — jump straight into the message.\
"""

    # Build alternating user/assistant messages from history.
    # The opener (first outbound) is included in the system prompt context above;
    # messages array starts from the first inbound reply.
    messages: list[dict] = []
    for msg in conversation_history:
        role = "user" if msg["direction"] == "inbound" else "assistant"
        if messages and messages[-1]["role"] == role:
            # Merge consecutive same-role messages (shouldn't happen but defensive).
            messages[-1]["content"] += "\n\n" + msg["content"]
        else:
            messages.append({"role": role, "content": msg["content"]})

    # Must start with user (inbound) — if first message is outbound, drop it
    # (it's already captured as context in the system prompt).
    while messages and messages[0]["role"] == "assistant":
        messages.pop(0)

    if not messages:
        raise ValueError("No inbound messages found to reply to.")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        temperature=0.7,
        system=[
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=messages,
    )

    return response.content[0].text.strip()


_OPENER_PROMPT = (PROJECT_ROOT / "prompts" / "opener.md").read_text(encoding="utf-8")


def regenerate_opener(
    prospect: dict,
    brief: str,
    current_draft: str,
    instruction: str,
) -> str:
    """Redraft an opener with a redirect instruction. Used by Telegram redraft handler.

    Args:
        prospect: dict with name, company, headline (optional), city/area.
        brief: research_brief markdown.
        current_draft: the existing opener Zico wants changed.
        instruction: what to change (e.g. "lead with founder operations angle").

    Returns:
        New opener text, ≤300 chars (LinkedIn connection-note limit).
    """
    from outreach.ingest.voice_samples import load_voice_samples

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    voice_samples = load_voice_samples()
    samples_text = "\n\n---\n\n".join(voice_samples[:10]) if voice_samples else ""

    user_content = f"""
Prospect info:
Name: {prospect['name']}
Company: {prospect.get('company', '')}
Headline: {prospect.get('headline', '')}
Location: {prospect.get('location') or prospect.get('city') or prospect.get('area') or 'Malaysia'}

Research brief:
{brief}

CURRENT DRAFT (preserve the voice, rhythm, and structure of this):
{current_draft}

REDRAFT INSTRUCTION FROM ZICO:
{instruction}

Voice samples (write exactly like this):
{samples_text}

Apply the redraft instruction. Keep the voice, rhythm, and length of the current
draft. Change only what the instruction specifies — leave everything else intact.
Stay under 280 characters (hard limit — sends fail above 300).
Output only the new opener text, no preamble or explanation.
""".strip()

    system = f"{_OPENER_PROMPT}\n\n{_VOICE_SPEC}\n\n{_HUMANIZE_RULES}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        temperature=0.5,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    return response.content[0].text.strip()
