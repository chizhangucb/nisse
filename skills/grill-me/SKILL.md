---
name: grill-me
description: Interview the owner relentlessly about a plan, design, or topic, checkpointing every answer to a brainstorm file so nothing is lost. Use when the owner wants to stress-test a plan, get grilled on a design, run a brainstorm or discovery session, extract what's in their head into a doc, or says "grill me".
---

# Grill Me

Interview the owner about every aspect of the topic until you reach shared understanding, walking each branch of the decision tree in dependency order. The real goal: **extract what's in their head into a durable, organized markdown file** so nothing is lost as context fills up. The file, not your context, is the source of truth.

## Setup (before the first question)

1. Create the capture file at `records/brainstorms/{YYYY-MM-DD}-{topic-slug}.md` in the hub (`date +%F` for the date). The capture ALWAYS lives in the hub, even when this skill runs from a satellite or any other cwd (resolve the hub via `AIOS_HUB`); never in project folders or satellite repos. A polished deliverable can move elsewhere later, the raw capture stays.
2. Write the header immediately: title, date, session goal, empty "Open flags" section.
3. Tell the owner where you're saving, one line. Then ask Q1.

## The checkpoint rule (non-negotiable)

After EVERY answer, BEFORE the next question: append a structured entry (question topic, key facts and decisions in the owner's words where wording matters, flags with owners), correct earlier entries a later answer changes, and only then ask on. Never batch multiple answers into one write. If context dies mid-session, the file already holds everything.

## Interview method

- **Strictly one question per turn. Never bundle questions**, even related ones; bundling is the classic failure mode of this skill. One turn = one question, answered, checkpointed, then the next.
- With each question, give your **recommended answer** (best inference from context) so the owner can confirm, correct, or redirect.
- Settle upstream decisions before the ones that depend on them.
- If a question is answerable by reading code, files, or a doc the owner handed over, do that instead of asking; surface only what's net-new.
- The owner can't answer something: capture it as a flag with the right owner and move on.
- Keep going until the owner says done or every branch is covered; near the end, offer a completeness backstop ("anything we haven't touched?").

## Capture file structure

```
# {Topic}: Brainstorm / Discovery Notes
Date: {date} · Goal: {one line}

## Summary / key decisions
(running synthesis, updated as you go)

## Q&A log
### Q1 - {topic}
- Asked: {question}
- Captured: {facts, decisions, in their words where it matters}
- Flags: {open item -> owner}

## Open flags (pending input)
- {item} -> {who can answer}
```

## At the end

Reread the capture for contradictions or gaps and reconcile; recap what's captured, what's flagged, and the next step. Decisions meeting the logging bar still get their block in `records/decisions.jsonl`, written in-flow.
