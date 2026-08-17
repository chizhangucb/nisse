# Wiki Operating Rules (shared)

Process contract shared by the wiki operations (wiki-ingest, wiki-distill, wiki-triage). Skill-specific rules live in each skill's own files; invariants in `wiki/CLAUDE.md`. Precedence: schema > this file > skill rules > skill.

- **Batch semantics.** Enumerate scope first (title, date, kind), confirm if ambiguous, then run without stops. The full pass runs per source; batch never waters down a per-source guard. One combined report at the end: one line per source, failures named never silently skipped, one failure does not abort the rest.
- **Boilerplate, binding on every operation:** write only inside `wiki/` (triage's one exception: Retire moves to repo-root `archives/`); no tracker, chat, or external writes; no git commit unless the owner asks; scratch only under repo-root `.tmp/`; deleting any wiki page takes the owner's explicit yes; an empty checkpoint is still reported honestly, never skipped.
- **Proper nouns.** Check `wiki/metadata/name_registry.md` first, then `context/about-team.md` and entity pages; a name matching nobody is usually an existing person misspelled. Unresolved names go to the checkpoint. Write the canonical name, or the name as heard with uncertainty visible, never a clean-looking guess. Never merge two names because they resemble each other. New-page follow-through: creating an entity/concept page also registers it where it will be looked up next, in the same pass: `metadata/index.md` always, and a `context/about-team.md` row when the entity is a team member.
- **Open-callout template.** Distill creates these per contradiction; triage resolves them:

  > [!question] Open: <topic>, <question>?
  > **One side:** claim (who) [[source]]
  >
  > **Other side:** claim (who) [[source]]
  >
  > **The question:** the fork, in one line
  >
  > **Status:** open since YYYY-MM-DD

  Resolution appends a dated `**Resolution:**` line inside the block and flips `**Status:**`; history kept, block stays put.
