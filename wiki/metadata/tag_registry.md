# Tag Registry

The one controlled vocabulary for wiki tags (`wiki/AGENTS.md`, Tags and name resolution). Subjects only, never interaction properties. Check slugs AND aliases here before minting a new tag; add the row first, then use the tag. Rules: nouns, singular, max 2 words, underscores.

Column order is load-bearing: `scripts/wiki_check.py` reads the first cell as the slug and the second as a comma-separated alias list. A slug that is not `[a-z0-9_]+` is ignored, so never decorate the slug cell.

| Slug | Aliases seen in the wild | Meaning |
|---|---|---|
| ci_pipeline | build_system, cicd | (example) continuous-integration tooling and flakes |
