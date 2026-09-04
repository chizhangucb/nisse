# Wiki Schema

The binding schema for the wiki, the knowledge layer of this operating system. The agent writes the wiki; the owner curates sources and directs analysis. This is the one schema file under `wiki/`; `wiki/CLAUDE.md` and `wiki/confidential/CLAUDE.md` only point here.

This file holds the invariants, violable by no actor, skill or not. Operations live in the skills (`wiki-ingest`, `wiki-distill`, `wiki-triage`) and their `references/` rules, read at run start. Precedence: this schema > skill rules > skill.

Mechanical rules here are enforced by `python3 scripts/wiki_check.py`. Semantic judgment (orphans, tag sprawl, stale truth) stays with `wiki-triage`.

## Layers and ownership

| Layer | Path | Who owns it |
|---|---|---|
| Raw sources | `raw/` | The owner. **Immutable.** The agent reads, never edits or deletes. |
| Wiki pages | `sources/`, `entities/`, `concepts/`, `synthesis/`, `confidential/` | The agent. Create, update, cross-link, maintain. |
| Archive | `archive/` | The agent. Cold storage for rotated evidence; uncapped. |
| Schema | `AGENTS.md` | Both. Co-evolved. |
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
entities/       people, companies, products (proper nouns; subtype field)
concepts/       ideas, mechanisms, frameworks (common nouns)
synthesis/      cross-source arguments, comparisons, open questions
confidential/   your most sensitive knowledge pages (lenses: docs/confidentiality.md)
archive/        rotated evidence, `<same-subpath>.md`, uncapped cold storage
metadata/       index.md, log.jsonl, sources.jsonl, tag_registry.md, name_registry.md
_templates/     page scaffolds, one per page kind; wiki-ingest reads the source-page ones
```

- Filenames `lowercase_with_underscores.md`. Living pages (entities, concepts, synthesis) carry no dates. Point-in-time records do: raw transcripts, brainstorms, and meeting source pages are `YYYY-MM-DD_<series_slug>.md`, source page slug identical to its raw file, series name not session topic. Clippings and documents keep original names.
- **Authorship decides the raw/ folder, never the capture tool or the subject.** Pasted external text is still clippings or documents; `brainstorms/` is exclusively the owner's own writing. Which world a source belongs to is `project:` metadata, never a raw/ split.
- **Re-transcription exception.** A retranscribed capture lands as `<slug>_asr.md` beside the untouched original; its source page keeps the unsuffixed series slug (the one case raw filename and source-page slug differ), and `origin:` names the retained mirror. Attribution is a claim: an unattributable turn is tagged `speaker best-guess (low confidence)`, never a silent guess.
- Metadata logs are append-only JSONL written only via `python3 scripts/wiki_ledger.py` (`append-log` | `append-source`), never hand-edited. `sources.jsonl` carries one row per meeting; query a series by its slug.
- Obsidian Flavored Markdown: `[[wikilinks]]`, `> [!note]` callouts, `#tag_slug` marks. Callout spacing: blank line before and after, a bare `>` line between bold-label sections inside. Nested lead-ins: a cluster is `- **Label**` with 2-space-indented children, no blank line between; never a bold label alone above flat bullets.

## Page kinds and required sections

Live-stream pages (entities, concepts, synthesis that take evidence) carry, top to bottom: `# Current truth (last updated: YYYY-MM-DD)` → `## Open decisions` → `> [!question] Open` callouts → `# Evidence`. Open items stay visible above the ledger. **The sections ARE the tier markers.** Static pages skip the tiers; add them on a second conflicting source.

Source pages carry: digest, takeaways, `# Signals` (self-sufficient; distill reads Signals, not raw), and `# Distilled` (one `[[page]] | what changed | what landed` line per page touched, or "(No durable updates.)").

Every page kind has a scaffold in `_templates/`. Start from it; the templates are checked as pages, so a template that drifts from this schema fails the suite.

Evidence bullet format:

```
- YYYY-MM-DD | claim | #tag_slug | Source: [[source_page]] (class)
```

Order date-ascending, oldest first. Re-sorting into date order is maintenance, not a rewrite. **Source class:** `(primary)` the owner was in the room; `(external)` someone else's published claim, unverified unless noted; `(inference)` agent synthesis.

Open-callout template (distill creates per contradiction, triage resolves):

```
> [!question] Open: <topic>, <question>?
> **One side:** claim (who) [[source]]
>
> **Other side:** claim (who) [[source]]
>
> **The question:** the fork, in one line
>
> **Status:** open since YYYY-MM-DD
```

Resolution appends a dated `**Resolution:**` line inside the block and flips `**Status:**`; history kept, block stays put. A resolution readable only inside the callout has not landed; triage folds it into `# Current truth`.

## Promotion

Triage is the only operation that promotes evidence into `# Current truth` (procedure in `wiki-triage`). `(primary)` can flip truth; `(external)` alone earns "reportedly". The first promotion creates the sections. Proposed truth is terse and stranger-readable, grouped by topic, overlapping points deduped; conflicts are stated, never averaged. A contradicted claim gets a Superseded callout (Rule 1). Resolving an Open block folds the answer into `# Current truth` the same pass and clears any truth line still calling the question open. A `synthesis/` page is always its own explicit yes, never bundled into a page promote; a yes covers that page, not the session.

## The Rules

1. **Never rewrite history, only append.** `raw/` read-only; `metadata/log.jsonl` and `# Evidence` append-only (governs content, not line order). A contradicted claim is never silently overwritten: add a `> [!warning] Superseded` callout naming old claim, new claim, source. Deleting any wiki page requires the owner's explicit confirmation.
2. **Every page earns its links.** No orphans: every new page gets >=1 inbound `[[wikilink]]` and links out to every entity/concept it mentions that has (or should have) a page. Mentioned 3+ times with no page: create or flag.
3. **Every claim carries its source and class.** Factual claims cite inline `claim [[source_page]]`; synthesis is marked `(inference)`; Evidence bullets carry a trust class. Disagreeing sources both get recorded plus an Open block; never a silent winner. Unsourced assertion is a bug.
4. **Every raw file becomes knowledge; the queue stays visible.** Ingest gives every raw file a source page (or ledger line), no orphan drops. Distill lands evidence on every affected page; `distilled:` (empty = pending) keeps the queue visible; a backlog older than ~2 weeks gets flagged.
5. **Retrieval is complete, or it is declared.** State full / partial / excerpts before writing; try the full-content path first. `retrieval:` warns the reader; a workaround is never reported as a clean read. `storage:` is a separate claim: `verbatim` (default) or `digest`, digest only when verbatim is impossible or the owner asks.
6. **Evidence and synthesis never move in the same pass.** Ingest/distill append `# Evidence` only. Triage is the only operation that rewrites `# Current truth`, only with the owner's in-session yes; triage never appends evidence.
7. **Sensitivity routes at write time, fail closed.** Define your lenses in `docs/confidentiality.md` and mirror them as `confidential:` values. Evidence matching a lens goes to `confidential/` pages, never open ones. Per bullet, not per source: a marked source still feeds open pages its non-sensitive evidence. Could go either way -> `confidential/`. Source pages stay in `sources/` even when marked. Linking is one-directional: a `confidential/` page may link out, but nothing links in with content. Nothing in `confidential/` feeds external output (`docs/confidentiality.md` governs).

**Boilerplate, binding on every operation:** write only inside `wiki/` (triage's one exception: Retire moves the page to `archive/`); no tracker, chat, or external writes; no git commit unless the owner asks; scratch only under repo-root `.tmp/`; no em dashes; deleting any page takes the owner's explicit yes; an empty checkpoint is reported honestly, never skipped.

**Batch semantics.** Enumerate scope first (title, date, kind), confirm if ambiguous, then run without stops. The full pass runs per source; batch never waters down a per-source guard. One combined report at the end: one line per source, failures named never silently skipped, one failure does not abort the rest.

## Frontmatter

```yaml
---
type: source | entity | concept | synthesis | archive
tags: [slug, slug]          # 3-5, canonical slugs only
project: work | personal | health | life
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [source_slug]      # omit on source pages
confidential: [slug, slug]  # empty, or your lenses from docs/confidentiality.md
---
```

- `project:` records which hat the owner wore when the source came into existence, never the subject. The list is closed: `work` (arrived through work channels), `personal` (one of the folders in `projects/`), `health`, `life` (the default: everything else). **Rename `work` to your company or practice slug** and update `KNOWN_PROJECTS` in `scripts/wiki_check.py` in the same pass; do not add a fifth value without recurring sources. Entities are shared across axes, never duplicated. Scalar by default; a rollup source may carry a list. Orthogonal to `confidential:`.
- `confidential:` is a list, most sensitive first; empty stays bare. Every mark is live: routing obeys the union; the list says which lenses to distill through, not that the page is sealed. The shipped lenses are examples: replace them with your own in `docs/confidentiality.md` and `CONFIDENTIAL_VALUES` in the checker.
- Source pages add: `origin:`, `ingested:`, `retrieval:`, `storage:`, `class: primary | external`, `distilled:` (empty = pending), optionally `via:`. Meeting source pages add `participants: []`, `context: internal | external`, `meeting_type:`. Retranscribed sources add `recovered:`. Entity pages add `subtype: person | org | product`. Markdown raw files and clipping source pages add `triaged:` (empty = queued).

## Tags and name resolution

- **Tags:** one controlled vocabulary in `metadata/tag_registry.md`: subjects only, never interaction properties. Check slugs AND aliases before minting; add to the registry first. Nouns, singular, max 2 words, underscores. 3-5 per page; inline `#tag_slug` uses the same slugs.
- **Names:** for a person, `python3 scripts/contacts.py resolve <name>` first (it reads `contacts/contacts.jsonl` and the anti-registry `contacts/not_names.jsonl`), then `context/about-team.md` and entity pages; for any other proper noun, `metadata/name_registry.md`. A name matching nobody is usually an existing person misspelled; a `not_name` result is never a person. Write the canonical name, or the name as heard with uncertainty visible, never a clean-looking guess; never merge two names because they resemble each other. Unresolved names go to the checkpoint. Resolution moves the record: a person gains a contact row or an alias (`contacts.py add` / `add-alias`), an artifact that is nobody gains a `contacts.py add-not-name` entry, any other proper noun gains a registry row, and the source page loses its `**Name gaps:**` line. Creating a page also registers it in `metadata/index.md` (and a `context/about-team.md` row for a team member) in the same pass.

## Word budgets and archive

- `# Current truth` stays under 250 words (whole section): every triage promotion replaces or consolidates; overflow demotes back to Evidence. Grouped by topic under nested bold lead-ins, not by evidence order; since triage rewrites it wholesale, regrouping is free.
- Living pages stay under ~2,000 words. Over budget, triage rolls the oldest folded Evidence (older than ~1 month, not in an open or unresolved-Superseded block) to `archive/<same-subpath>.md` (`type: archive`), leaving a dated pointer. Rotation, not deletion; triage owns it, distill never archives. **The archive is uncapped cold storage**, read only when a live page's pointer sends you there.
- **File-class word budgets** (checked at triage): living wiki pages 2,000; this schema 2,000; any SKILL.md 500; skill references 700. Sediment homes: ops detail to skill references, item facts to the item's page.

## Operations

Each verb is a skill; the skill and its `references/` own the process detail.

- `ingest <paths | URLs | pasted text>` (skill `wiki-ingest`): mirror to `raw/`, write the source page, update metadata; `distilled:` stays empty.
- `distill [<source> | pending]` (skill `wiki-distill`): mine source pages into `# Evidence` appends, one checkpoint before writing. Never touches `# Current truth`.
- `triage` / `lint` (skill `wiki-triage`): promote evidence into `# Current truth`, queue dispositions, health checks; the only op that rewrites truth.
- `query <question>`: read `metadata/index.md`, grep `metadata/sources.jsonl` for meetings (never wholesale), open relevant pages, answer with `[[page]]` citations, `# Current truth` first. Good answers become `synthesis/` pages.
