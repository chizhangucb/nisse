---
name: wiki-distill
description: Distill ingested sources into wiki knowledge - mine undistilled source pages into append-only evidence across entity, concept, and synthesis pages, batch-native with one checkpoint. Use whenever the owner says distill, distill the pending sources, process the queue, extract the evidence, or update the entities from recent meetings, or names specific sources to distill. Also the follow-up step after wiki-ingest lands sources. Works on one source or the whole pending queue in a single pass. Not for landing new sources (wiki-ingest), not for promoting evidence into current truth or health checks (wiki-triage), not for answering questions from the wiki.
---

Batch-native extraction pass: **queue → read → draft → checkpoint → write → report**; one checkpoint covers the whole batch, nothing is written before the owner's yes.

Read `wiki/CLAUDE.md`, `wiki/rules.md`, and `references/distill-rules.md` first, in full. Precedence: schema > shared rules > skill rules > this file.

## Is / is not

| Yes | No |
|-----|-----|
| Insert `# Evidence` bullets in date order, pipe format, each with source and trust class | Rewriting or deleting existing bullets, or touching `raw/` |
| Create missing entity/concept pages with `subtype:` set and inbound links | Touching `# Current truth` or `## Open decisions`, even when new evidence obviously changes them (wiki-triage) |
| Route lens-matching and could-go-either-way bullets to `confidential/` pages | Landing new sources (wiki-ingest) |
| Open a `> [!question] Open` block per contradiction, no silent winner | Answering questions from the wiki |

## The pass

1. **Build the queue:** scan `wiki/sources/` for empty `distilled:`. The owner names sources, or "pending" means all; a single source is a batch of one. Confirm scope if ambiguous.
2. **Read each source fully.** `# Signals` is the primary input; go back to the raw file when signals are thin or ambiguous.
3. **Draft, then checkpoint with the owner:** one package for the whole batch (contents table in `references/distill-rules.md`), cross-source dedup, proper nouns per `wiki/rules.md`.
4. **Write, after the yes:** insert Evidence bullets in date order on each affected page, create the approved new pages (with inbound links), fill each source's `# Distilled` section, stamp `distilled:` to today, mint approved tags into the registry, append the pass to `wiki/metadata/log.md`.
5. **Report the diff:** sources distilled, pages created/updated, contradictions opened, anything routed to `confidential/` (named to the owner only).
