---
name: wiki-ingest
description: Land sources in the wiki, one or many per run - meeting transcripts (pasted or from a wired connector), clipped articles or URLs, PDFs or decks, or notes the owner wrote themselves. Mirrors each into raw/, writes its source page (digest, takeaways, signals), and queues it for distillation. Use whenever the owner says ingest this or these, add or put this in the wiki, land these files, process my meetings or transcripts, clip this article, or file this note, idea, or document into the wiki or knowledge base. Any request that gets source material INTO the wiki is this skill, even if the word wiki never appears. Not for extracting evidence to entity pages (wiki-distill), not for answering questions from the wiki, not for triage.
---

Batch-native landing pass: **enumerate → acquire → mirror → source page → metadata → report**. Read `wiki/AGENTS.md` and `references/ingest-rules.md` first, in full; precedence: schema > skill rules > this file.

## Is / is not

| Yes | No |
|-----|-----|
| Mirror every source into `raw/`; immutable once written | Editing or deleting anything already in `raw/` |
| Write each source page: digest, takeaways, a generous `# Signals` | Evidence extraction; entity, concept, synthesis pages (wiki-distill) |
| Set `confidential:` at ingest, fail closed (Rule 7) | Touching `# Evidence` or `# Current truth` |
| Queue for distillation: `distilled:` left empty | Answering questions from the wiki |

## Where inputs land

Authorship decides the folder, never the capture tool or subject.

| The owner gives | Raw destination |
|---|---|
| Meeting transcript (pasted, file, or connector) | `wiki/raw/transcripts/` |
| URL or clipped article | `wiki/raw/clippings/` |
| PDF or deck | `wiki/raw/documents/` |
| Something the owner wrote themselves | `wiki/raw/brainstorms/` |

## The pass

1. **Check the index:** `wiki/metadata/index.md` for non-meetings, grep `wiki/metadata/index/` for meetings. Already ingested → stop and say so.
2. **Acquire and read fully; declare retrieval** (full / partial / excerpts) before writing anything. A workaround is never a clean read (Rule 5).
3. **Judge the tier** (meetings only; policy in `references/ingest-rules.md`). Ledger tier: still land the raw file and one annotated monthly-index line, but skip the source page. The owner saying "full page" overrides.
4. **Land the raw file** verbatim, per the naming rules in `references/ingest-rules.md`. Never edit what you mirror.
5. **Write the source page** from the template (`wiki/_templates/source-page-meeting.md` or `-general.md`); the templates' inline comments carry the per-section rules. Set `project:`, `participants`, `context`, `meeting_type`; set `confidential:` NOW, fail closed, and say the call in the report. Flag name gaps per `references/ingest-rules.md`. Extract `# Signals` generously. Leave `distilled:` empty.
6. **Update metadata:** monthly index line (meetings) or `index.md` (non-meetings); append one row to `wiki/metadata/log.jsonl` and, for a new source, one row to `wiki/metadata/sources.jsonl`. Append only: one JSON object per line, never rewrite an existing line.
7. **Report** per rules.md batch semantics; close with the undistilled queue count.
