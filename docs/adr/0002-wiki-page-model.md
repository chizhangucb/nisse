---
status: accepted
date: 2026-09-03
---

# Wiki page model: three tiers, append-only evidence, one schema file

The wiki is the knowledge layer: raw sources turned into cited evidence turned into current truth, so answers cite a durable slug instead of re-deriving from scratch. Its rules had been split across a schema file, a shared rules file, and a product contract, with the same invariants restated and a standing "schema wins on divergence" note admitting they could drift. We decided to record the page model here and collapse the schema to one binding file, `wiki/AGENTS.md`, with `wiki/CLAUDE.md` a symlink to it, the same shape as the repo root. This mirrors the upstream repo's ADR-0002.

The model:

- **Three tiers of truth.** A live page carries `# Evidence` (append-only), `# Current truth` (settled, under 250 words), and rarely a `synthesis/` page. The sections are the tier markers; each is written by a different operation. Distill appends Evidence; only triage rewrites Current truth, only with the owner's in-session yes. Evidence and synthesis never move in the same pass.
- **Append-only evidence.** A contradicted claim is never overwritten: it gets a Superseded callout naming old claim, new claim, and source. Every bullet carries a source and a trust class (primary, external, inference).
- **Archive rotation.** A living page stays under about 2,000 words. Over budget, triage rolls the oldest folded evidence to `wiki/archive/<same-subpath>.md` and leaves a dated pointer. Rotation, not deletion.
- **Sources as immutable mirrors.** Every raw item is mirrored verbatim into `raw/` (the owner's, never edited by the agent) and gets one source page. Sensitivity routes per bullet at write time, fail closed, to `confidential/`.

## Considered options

- **Keep the three wiki-root files.** Rejected: one binding file removes divergence instead of managing it.
- **Fold operations into the schema.** Rejected: the schema holds invariants; each skill's `references/` holds its process, read at run start.
- **Free-text `project:` field.** Rejected: the checker needs a closed list. nisse ships `work | personal | health | life`; the owner renames `work` to their company slug.

## Consequences

- `wiki/AGENTS.md` is the single schema. `scripts/wiki_check.py` enforces its mechanical rules; a fixture test and a run over the shipped example pages both fail CI on any violation.
- Metadata logs are written only through `scripts/wiki_ledger.py`.
- `wiki/_templates/` holds a template for every page kind; the checker validates templates as pages.
- The root `CONTEXT.md` carries the wiki terms; there is no separate wiki glossary.
- Confidential routing ships with generic example lenses the owner replaces.
