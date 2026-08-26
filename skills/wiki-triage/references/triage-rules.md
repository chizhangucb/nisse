# Triage rules

Process rules specific to wiki-triage. Shared rules live in `wiki/rules.md`; invariants and precedence in `wiki/CLAUDE.md`.

Mechanical checks come from `scripts/hygiene_check.py` (orphans, page budgets, truth staleness, undistilled backlog, tag sprawl, ingest gaps); read its wiki-health findings, never re-derive them. Triage owns the judgment half below.

- **Promotion semantics.** `(primary)` can flip truth; `(external)` alone earns "reportedly". First promotion creates the sections. Proposed truth is terse, stranger-readable, grouped by topic (not evidence order); dedupe overlapping points. Conflicts stated, never averaged. Contradicted claims get a Superseded callout (schema Rule 1). Resolving an Open block also folds the answer into `# Current truth` in the same pass and clears any truth line still calling the question open. New facts the owner surfaces mid-triage park for wiki-ingest. A `synthesis/` page is always its own explicit yes, never bundled into a page promote. A yes covers that page, not the session.
- **Dispositions.** One per queue item, one-line reason each:

  | Disposition | Meaning | `triaged:` |
  |---|---|---|
  | Promote | wiki-worthy now; hand to wiki-distill | today |
  | Keep | still maturing, stays queued (defers the decision) | empty |
  | Skip | reviewed, no wiki value, permanently | today + skip note |
  | Retire | move to repo-root `archives/`; per-item explicit yes, never a bulk yes | today |

  `triaged:` is set only when a decision was made.
- **Evidence archival.** Living page over ~2,000 words: roll the oldest largely-folded Evidence (older than ~1 month, not inside an open block) to `wiki/annex/<same-subpath>.md` (`type: annex`, dates and cites kept), leaving a `> [!note]` pointer atop the live `# Evidence`, until under budget or nothing eligible remains. Nothing eligible: flag it, not fixed. Propose at checkpoint; distill never archives.
- **Write discipline.** Only what the owner approved. Truth and Open-decisions rewrites dated today, `updated:` bumped; tag merges make the old slug an alias of the canonical, retag frontmatter, leave historical inline `#tags` untouched; `wiki/metadata/index.md` updated for created or retired pages; one `triage` recap row appended to `wiki/metadata/log.jsonl` via `scripts/aios_ledger.py append-log` (`--op triage`). Never re-propose what the owner declined, absent new evidence.
- **Health checks (judgment).** Ranked, leakage on top, each with a proposed fix or an honest "no action worth taking":

  | Check | What fires it |
  |---|---|
  | Contradictions | disagreeing bullets, or bullet vs current truth, without a `> [!question] Open` callout |
  | Superseded claims | overturned by newer sources, callout missing |
  | Pageless mentions | the script's unminted-target findings, read as a batch: what page do they collectively reach for? Page creation is wiki-distill's job |
  | Confidential leakage | Rule 7 material outside `confidential/`; escalate on top; remediate with the owner's yes (the one sanctioned Rule 1 exception) |
  | Page length | over-budget pages from the script: propose evidence archival, or flag if nothing eligible |
  | Gaps | questions the wiki keeps almost answering; suggest sources, don't fetch |
