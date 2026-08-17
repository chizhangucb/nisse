# Distill rules

Process rules specific to wiki-distill. Shared rules live in `wiki/rules.md`; invariants and precedence in `wiki/CLAUDE.md`.

- **Checkpoint package.** One package covering the whole batch, shown before any write:

  | Part | Contents |
  |---|---|
  | Evidence | proposed bullets, grouped by destination page, deduped across sources |
  | Pages | to create (with inbound links) and to update |
  | Tags | to mint, checked against slugs AND aliases in `wiki/metadata/tag_registry.md` |
  | Routing | Rule 7: lens-matching and could-go-either-way bullets to `confidential/` |
  | Contradictions | each as a proposed Open block, no silent winner |
  | Names | flagged or distrusted proper nouns: resolved, or carried with uncertainty visible |

  "No durable evidence" is legitimate; never pad. Garbled fragments never become evidence; never accept a proper noun the source page flagged.
- **Signal targets.** A `**[[target]]**` prefix on a signal is a hint, never a constraint; override wrong prefixes without ceremony. **A target resolving to no existing page is a decision:** create the page, route to a named existing page, or flag and leave the evidence unwritten, named at checkpoint with why. Never quietly substitute a near-enough page; never satisfy a common-noun target with a person page.
- **Evidence bullets are atomic and plain.** One claim per bullet; split a multi-claim source moment into separate bullets on the same date. State what was said or observed, no ranking or framing; that judgment belongs in Current truth, added by triage. New Open callouts go above `# Evidence`, not appended after the ledger.
- **`# Distilled` line format:** `- [[page]] | <what changed> | <one line of what landed>`. `(No durable updates.)` stays the honest zero-evidence answer.
- **Report the overrides.** The diff report lists every unresolved or redirected target and where it went, plus anything routed to `confidential/`. A routing call that appears nowhere cannot be reviewed.
