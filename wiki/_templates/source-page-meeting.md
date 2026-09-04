---
type: source
tags: []                # 3-5 canonical slugs from wiki/metadata/tag_registry.md
project:                # work | personal | health | life
created:
ingested:
origin:                 # capture-tool URL or raw/transcripts/ path
via:                    # fireflies | clipper | fetcher | paste
retrieval:              # full | partial | excerpts
storage: verbatim       # meetings are always verbatim; digest only if no transcript retrievable
distilled:              # empty = awaiting wiki-distill; set to date when distilled
class: primary
confidential:           # empty, or a list: [finance] | [personnel] | [legal] | [finance, personnel] ...
participants: []
context:                # internal | external
meeting_type:           # 1:1 | team | leadership | customer | partner | vendor | investor | interview
# recovered:            # only on retranscribed sources; a block with engine + date subkeys
---

# Context

- Goal:
- Background:
- Deadlines:            # what expires and when. Hard dates, expiries, and stated windows all count. "none" is valid and common. Two or more items = a parent "- Deadlines:" bullet with one indented sub-bullet each, never one semicolon-run paragraph.

<!-- Rule 7 callout goes here, and ONLY when the page carries a confidential: mark or a sensitive
     category surfaced and was ruled out. Nothing sensitive in the content = no callout at all.

> [!note] Rule 7 routing, set at ingest
> Which marks the page carries and why. Name what was considered and rejected too. Mark in list
> form matching frontmatter; three sentences max; one box per page, all routing prose inside it.
-->

# Atmosphere

<!-- Observable behaviour only: who spoke, who deferred, who hedged, who volunteered, stated
     feelings, interruptions, register. Not motive, never mood-reading. One to three sentences.
     Never mined as evidence. "(Nothing notable.)" is expected on most internal meetings. -->

(Nothing notable.)

# Summary (factual)

<!-- Thread under bold labels when the meeting has 3+ distinct topics or this list runs 10+
     bullets. Otherwise keep it flat. Labels are nouns from the meeting, not invented categories.
     Each label is a parent bullet ("- **Label**") with 2-space-indented child bullets, no blank
     line between them. When a bullet's prefix repeats its label exactly, drop the prefix; keep
     prefixes that add a speaker or qualifier. -->

-

# Decisions

- (None)

# Action Items

<!-- Grouped by owner: whoever accepted the item, not whoever it concerns. Verb first, literal to
     what was said. A state someone is in is not an action item. External owners get their
     affiliation once. Render an "Unassigned" group whenever it is non-empty; an unowned action
     is a finding, not a gap in the notes. -->

- (None)

# Unresolved Points

- (None)

# Signals

Primary distill input. Extract generously, with attribution; subtle or ambiguous signals included.

<!-- Format: - **[[target]]** | Speaker (MM:SS-MM:SS): signal
     Several targets separate with commas before the pipe.
     Target is the page this most likely feeds. **target unclear** is allowed and is often the
     interesting one; a signal may name several targets. The target is a hint for wiki-distill,
     never a constraint. Order by the same threads as Summary, chronological within each thread. -->

- (None)

# Transcript Link

-
<!-- Tool-pointer line + `Raw mirror:` + `Excluded captures:`. Pointer = `<Tool>: <url>`, or
     `<Tool>: no shareable URL; file ID <id>` when the capture tool exposes none. -->

<!-- One callout, only if any caveat applies. Blank line before and after the whole block; a bare
     `>` line between each labelled section. Labels in this order; drop the ones that do not:

> [!warning] Capture caveats
> **Retrieval:** two sentences, hard cap. What is covered, what is missing, one clause of why, and
> "unknown, not absent" when a chunk is lost. No capture IDs or retry counts.
>
> **Speaker labels unreliable:** attribution or dedupe problems that qualify the whole page, or no diarization at all (the capture carries no speaker field); attributions are then content-inference.
>
> **Name gaps:**
> - proper nouns the capture rendered unreliably: variants, best read, for distill to resolve
> - anonymous speakers the knowledge layer supports a read for: `Speaker N = likely <Name>` tagged `**speaker best-guess (low confidence)**` (rule in wiki-ingest `references/ingest-rules.md`)
-->

# Distilled

Filled by wiki-distill: every wiki page this source's distillation touched, what changed there, and what landed.
Format: `- [[page]] | Evidence +N | one line of what landed`.

- (No durable updates.)
