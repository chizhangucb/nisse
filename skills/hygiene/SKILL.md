---
name: hygiene
description: Workspace hygiene sweep - runs the deterministic checker in scripts/hygiene_check.py (filesystem cruft, git hygiene, freshness, doc budgets, structural loose ends, wiki health mechanics) and walks the owner through confirm-to-fix. Use whenever the owner says run hygiene, clean up the workspace, scan for cruft, tidy the repo, check workspace health, or find stale files. Not for wiki truth promotion or semantic health judgment (wiki-triage).
---

Routing stub: the judgment is thin, the mechanics live in the script.

1. Run `python3 scripts/hygiene_check.py` from the repo root and read the findings.
2. Present them grouped as the script prints them, worst first. `auto-safe` findings can be fixed in one approved batch; `judgment` findings get one line of recommendation each.
3. Fix only what the owner approves, then re-run the script to confirm clean. Never delete anything without an explicit yes, even under "clean it all up".
4. Wiki-health findings that need semantic judgment (contradictions, leakage, truth promotion) hand off to wiki-triage; say so instead of half-doing them here.
