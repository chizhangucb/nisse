# Wiki Schema

LLM-maintained wiki, the knowledge layer of this operating system. The agent writes the wiki; the owner curates sources and directs analysis.

This file holds the invariants, violable by no actor, skill or not. Operations are governed by `wiki/rules.md` (shared process contract) plus each skill's own rules, read at run start. Precedence: this schema > `wiki/rules.md` > skill rules > skill.

## Layers

| Layer | Path | Who owns it |
|---|---|---|
| Raw sources | `raw/` | The owner. **Immutable.** The agent reads, never edits or deletes. |
| Wiki pages | `sources/`, `entities/`, `concepts/`, `synthesis/`, `confidential/` | The agent. Create, update, cross-link, maintain. |
| Schema | `CLAUDE.md` | Both. Co-evolved. |
| Meta | `metadata/` (index, log, tag_registry, name_registry) | The agent. Catalog, chronology, vocabulary, names. |

## Folders and naming

```
raw/            immutable, split by provenance
  transcripts/  ALL meeting transcripts, any capture tool; flat; gitignored (local-only)
  clippings/    mirrored web content, any fetcher
  documents/    PDFs and decks: partner/customer material, papers, reports
  brainstorms/  content the owner authored themselves
  assets/       images from clipped articles
sources/        one page per raw item: digest + takeaways + signals
entities/       people, companies, products (proper nouns)
concepts/       ideas, mechanisms, frameworks (common nouns)
synthesis/      cross-source arguments, comparisons, open questions
confidential/   your most sensitive knowledge pages (categories: governance/confidentiality.md)
annex/          rotated evidence overflow from living pages, mirror-pathed
metadata/       index.md, log.jsonl, sources.jsonl, tag_registry.md, name_registry.md
  index/        monthly source-index shards (sources-YYYY-MM.md), the human-readable companion to sources.jsonl
```

- Filenames `lowercase_with_underscores.md`. Living pages (entities, concepts, synthesis) carry no dates. Point-in-time records do: raw transcripts, brainstorms, and meeting source pages are `YYYY-MM-DD_<series_slug>.md`, source page slug identical to its raw file, series name not session topic (topics go in the index annotation). Non-meeting source pages get dateless topic slugs; clippings and documents keep original names.
- Obsidian Flavored Markdown throughout: `[[wikilinks]]`, `> [!note]` callouts, `#tag_slug` marks. Blank line before and after every callout.
- **Authorship decides the raw/ folder, not the capture tool** (pasted external text is still clippings/documents; brainstorms/ is exclusively the owner's own writing). **Subject never decides the folder**: which world a source belongs to is `project:` metadata, never a raw/ split.

## The Rules

**Rule 1 - Never rewrite history, only append.**
`raw/` read-only; the wiki log (`metadata/log.jsonl`, appended only via `python3 scripts/aios_ledger.py append-log ...`, a deny hook blocks raw edits) and `# Evidence` sections append-only. Pages get revised, but a contradicted claim is never silently overwritten: add a `> [!warning] Superseded` callout naming old claim, new claim, and source. Deleting any wiki page requires the owner's explicit confirmation.
Living pages stay under ~2,000 words. Over budget, triage rolls the oldest folded Evidence (older than ~1 month, not inside an open block) to `annex/<same-subpath>.md`, leaving a dated pointer. Rotation, not deletion; triage owns it, distill never archives.

**Rule 2 - Every page earns its links.**
No orphans: every new page gets at least one inbound `[[wikilink]]` and links out to every entity/concept it mentions that has (or should have) a page. Mentioned 3+ times with no page: create or flag.

**Rule 3 - Every claim carries its source and class.**
Factual claims cite inline: `claim [[source_page]]`. Agent synthesis is marked `(inference)`. Evidence bullets carry a trust class (below). Disagreeing sources both get recorded plus a `> [!question] Open` block; never pick a winner silently. An unsourced assertion is a bug.

**Rule 4 - Every raw file becomes knowledge; the queue stays visible.**
Ingest: every raw file gets a source page (digest, takeaways, signals) plus index and log updates, no orphan drops. Distill: evidence lands on every affected living page (typically 5-15 per source); may batch, but `distilled:` (empty = pending) keeps the queue visible; a backlog older than ~2 weeks gets flagged. Every source page ends with `# Distilled`: one `[[page]] | what changed` line per page touched, or "(No durable updates.)".

**Rule 5 - Retrieval is complete, or it is declared.**
Before writing anything, state what was retrieved: full, partial, or excerpts; try the full-content path first. `retrieval:` in frontmatter warns the reader; partial also adds a `**Retrieval:**` line naming the gap. A workaround is never reported as a clean read.

**Rule 5b - Retrieval and storage are different claims.**
`retrieval:` = what the agent read. `storage:` = what raw/ holds: `verbatim` or `digest` (agent extraction). Default verbatim; digest only when verbatim is impossible (paywall, DRM, no transcript) or the owner asks, said explicitly.

**Rule 6 - Evidence and synthesis never move in the same pass.**
Ingest/distill appends `# Evidence` only, never touches `# Current truth`. Triage is the only operation that refreshes `# Current truth`, only with the owner's approval in-session. Hard boundary both directions: triage never appends evidence.

**Rule 7 - Sensitivity routes at write time, fail closed.**
- Define your sensitive lenses in `governance/confidentiality.md` and mirror them as `confidential:` frontmatter values. Evidence matching a lens goes to `confidential/` pages, never open ones.
- To open pages: everything else.
- **Per bullet, not per source**: a `confidential:`-marked source still feeds open pages with its non-sensitive evidence. The mark means "distill with Rule 7 glasses on".
- **Could go either way → `confidential/`.**
- **Source pages stay in `sources/` even when marked.** `confidential/` holds curated knowledge pages, never meeting digests; the mark, not the folder, routes sensitive evidence at distill.
- Confidential pages may link out; nothing links in with content. Nothing in `confidential/` ever feeds external output (`governance/confidentiality.md` governs).

## Three tiers of truth

Live-stream pages carry: `# Evidence` (append-only, ingest/distill) → `# Current truth (last updated: YYYY-MM-DD)` + `## Open decisions` (rewritten only in triage, with the owner's yes) → `synthesis/` pages (rare, explicit approval). **The sections ARE the tier markers.** Static pages skip the tiers; add them on a second conflicting source.

Page order top to bottom: `# Current truth` → `## Open decisions` → `> [!question]` Open callouts → `# Evidence`. Open items stay visible above the ledger. Current truth is grouped by topic, not by evidence order; since triage rewrites it wholesale, regrouping is free. **`# Current truth` stays under 250 words**: every triage promotion replaces or consolidates, and overflow demotes back to Evidence.

Resolved `> [!question] Open` blocks stay where they are, Resolution line appended and `**Status:**` flipped; the same triage pass folds the answer into `# Current truth`.

## Evidence format

```
- YYYY-MM-DD | claim | #tag_slug | Source: [[source_page]] (class)
```

Classes: `(primary)` the owner was in the room; `(external)` someone else's published claim, unverified unless noted; `(inference)` agent synthesis.

Order: date-ascending, oldest first, stable within a date. Re-sorting into date order is maintenance, not a rewrite.

## Tags

One controlled vocabulary, governed by `metadata/tag_registry.md`: subjects only, never interaction properties. Check slugs AND aliases before minting; add to the registry first. Rules: nouns, singular, max 2 words, underscores. 3-5 per page; inline `#tag_slug` on bullets uses the same slugs.

## Frontmatter

```yaml
---
type: source | entity | concept | synthesis | annex
tags: [slug, slug]          # 3-5, canonical slugs only
project: <your-axis-values> # which hat you wore when the source arrived; define your own
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [source_slug]      # omit on source pages
confidential: [slug, slug]  # empty, or your lenses from governance/confidentiality.md
---
```

- **`confidential:` is a list, not a scalar**: empty stays bare, non-empty is always a YAML list, most sensitive first. Every mark is live: the list says which lenses to distill through, not that the page is sealed.
- **`project:` records which hat the owner was wearing when the source came into existence, never the subject.** Define a small set of values (e.g. `work`, `side_projects`, `health`, `life`) and hold the line; minting a new value requires recurring sources. Entities are shared across axes, never duplicated. Scalar by default; a rollup source spanning worlds may carry a list.
- Source pages add: `origin:`, `ingested:`, `retrieval:`, `storage:`, `class: primary | external`, `distilled:` (empty = awaiting distill), optionally `via:` (paste | clipper | fetcher | connector name).
- Meeting source pages add: `participants: []`, `context: internal | external`, `meeting_type:` (1:1 | team | customer | partner | investor | interview | talk | ...).
- Entity pages add: `subtype: person | org | product`. Flat `entities/` folder; the field makes a later split mechanical.

## Operations

**`ingest <paths, URLs, or pasted text>` (skill: wiki-ingest).** Land sources: mirror to raw/, source page, and append to `metadata/sources.jsonl` + `metadata/log.jsonl` (via `aios_ledger.py append-source` / `append-log`; a deny hook blocks raw edits). No entity/concept writes; `distilled:` stays empty. Every meeting capture lands verbatim in `raw/transcripts/` (gitignored); source pages are earned (full page vs an index ledger line for low-signal captures).

**`distill [<source> ... | pending]` (skill: wiki-distill).** Mine undistilled source pages into `# Evidence` appends, one checkpoint with the owner before writing. Never touches `# Current truth` (Rule 6).

**`query <question>`.** Read `metadata/index.md`, grep `metadata/index/` for meeting sources (never wholesale) → open relevant pages → answer with `[[page]]` citations, `# Current truth` first. Good answers become `synthesis/` pages.

**`triage` / `lint` (skill: wiki-triage).** Weekly-ish, interactive: propose → the owner approves → write. Truth promotion, queue dispositions, health checks; the one operation allowed to rewrite `# Current truth`.

## Hygiene

- One-off scripts, logs, scratch files go ONLY under repo-root `.tmp/` (gitignored), never into `wiki/` or other content folders.
- Style per `governance/communication-style.md`. Wiki pages are terse and factual, not essayistic.
- File-class word budgets, checked by the hygiene script: living wiki pages 2,000; this schema 2,000; `wiki/rules.md` 400; any SKILL.md 500. Sediment homes: stories to the decisions log (`records/decisions.jsonl`), ops detail to skill references, item facts to the item's page.
