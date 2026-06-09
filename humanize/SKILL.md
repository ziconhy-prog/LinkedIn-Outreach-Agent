---
name: humanise-text
description: Transform AI-generated or robotic-sounding text into natural, human-written content. Use when the user asks to humanize text, make writing sound more natural, remove AI patterns, rewrite content to sound human, avoid AI detection, or make text less robotic. Also use when reviewing or editing content that exhibits overly formal, mechanical, or AI-typical writing patterns. Also triggers on "humanise-text install" or "humanise-text setup" to run the install wizard.
---

# Humanise Text Skill

Transform AI-generated or robotic text into natural, human-written content by eliminating mechanical patterns and introducing realistic human writing characteristics.

## Install

If the user says `/humanise-text install` or `/humanise-text setup`, run this install wizard instead of the normal workflow.

### Step 1: Verify files

Check that the skill files are in place:

```bash
ls <skill_path>/SKILL.md <skill_path>/references/overused-ai-patterns.md
```

If both files exist, report success. If either is missing, tell the user which file is missing and that they need to re-extract the skill package to `~/.claude/skills/humanise-text/`.

### Step 2: Verify the reference file is readable

```bash
head -5 <skill_path>/references/overused-ai-patterns.md
```

Confirm it starts with `# Overused AI Patterns Reference`.

### Step 3: Report status

Print a summary:

```
Humanise Text — Install Complete

  Files:     OK (SKILL.md + references/overused-ai-patterns.md)
  Dependencies: None required
  Status:    Ready to use

Try it: /humanise-text then paste any text you want to humanize.
```

No further steps needed. This skill is fully self-contained.

---

## Core Objectives

Create content that reads like it was written by a human: naturally, casually, and with a realistic thought process.

**Primary goals:**
1. Eliminate AI-typical rhetorical constructions
2. Vary sentence structure and pacing
3. Add subtle human imperfections
4. Avoid perfectly balanced arguments
5. Skip overused words, phrases, and constructions entirely
6. Write naturally without forced formatting

## Process

### Step 1: Read the Reference File

Before humanizing any text, always read the complete reference file to refresh knowledge of prohibited patterns:

```bash
cat <skill_path>/references/overused-ai-patterns.md
```

This file contains:
- Five major rhetorical constructions to avoid
- Comprehensive lists of overused words and their replacements
- Prohibited expressions and phrases
- Construction patterns that signal AI writing

### Step 2: Analyze the Input Text

Identify which AI patterns appear in the original text:
- Note specific rhetorical constructions (elliptical setups, revelation hooks, etc.)
- Mark overused transition words
- Flag business jargon and marketing buzzwords
- Identify any em-dashes
- Spot "It's not X, but Y" constructions

### Step 3: Apply Humanization Techniques

**Vary sentence structure:**
- Mix long and short sentences
- Break up perfectly smooth flows with occasional interruptions
- Avoid rhythmic patterns that feel too deliberate

**Add subtle imperfections:**
- Use hesitation words when appropriate: "perhaps", "I think", "seems like"
- Include cautious qualifiers if they fit the writing style
- Allow slight redundancy that feels natural

**Avoid perfect symmetry:**
- Don't balance every argument with equal weight
- Let some thoughts trail off or shift direction
- Allow tangential observations that a real person might include

**Use light personalization:**
- Mention small reactions or observations
- Include mild opinions when appropriate
- Reference experiences that feel plausible

**Introduce mild ambiguity:**
- Humans aren't always consistent
- A slight shift in tone or perspective adds realism
- Avoid being overly precise about everything

**Format naturally:**
- Break paragraphs where it feels intuitive
- Avoid rigid or textbook-like structure
- Let the content flow rather than forcing organization

### Step 4: Replace Prohibited Content

For every prohibited word, expression, or construction:
1. Identify the specific item from the reference file
2. Select an appropriate replacement from the provided alternatives
3. Rewrite the sentence naturally with the replacement

**Critical rule:** Avoid em-dashes completely. Use periods, commas, colons, or restructure sentences instead.

### Step 5: Self-Audit and Correct

After creating the draft:

1. Scan your own text line by line
2. Create a list of any phrases where you used:
   - Rhetorical constructions from the reference file
   - Overused words from the reference file
   - Prohibited expressions
   - Em-dashes
   - Perfect balanced oppositions

3. For each flagged item, provide:
   - The problematic phrase
   - Why it's problematic
   - A corrected version

4. Rewrite the complete text with all corrections applied

**Do not deliver the final output until this self-audit and rewrite is complete.**

## Example Transformation

**Before (AI-typical):**
"Here's the truth no one talks about—AI isn't replacing jobs, it's amplifying productivity. Moreover, the paradigm shift we're seeing isn't just about automation. It's about empowerment. The best part? You can leverage these cutting-edge tools seamlessly."

**Problems identified:**
- "Here's the truth no one talks about" (Revelation Hook)
- Em-dash usage
- "AI isn't replacing X, it's Y" (Philosophical Reduction)
- "Moreover" (prohibited transition word)
- "paradigm shift" (marketing buzzword)
- "It's about X" (part of Big Contrast construction)
- "The best part?" (Elliptical Setup)
- "leverage" (business jargon)
- "cutting-edge" (marketing buzzword)
- "seamlessly" (business jargon)

**After (humanized):**
"AI tools are changing how we work, mostly by making people faster at what they already do. The shift goes beyond simple automation. These tools help people get more done. You can start using them pretty easily, and they integrate with most existing workflows."

## Key Reminders

- Always read the reference file first
- Replace ALL prohibited items, not just some
- Complete the self-audit before delivering final output
- Keep language neutral but natural
- Focus on realistic tone and pacing
- Avoid slang unless specifically requested
- Never use em-dashes

## When Humanizing Different Content Types

**Casual conversation:** Keep it short, varied, and natural. Skip lists and formal structure.

**Professional writing:** Maintain professionalism but avoid business jargon entirely. Use clear, direct language.

**Creative content:** Allow more personality and imperfection to show through.

**Technical content:** Stay accurate but explain things naturally rather than mechanically.

**Marketing copy:** Be compelling without resorting to buzzwords or empty enthusiasm.
