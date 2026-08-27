---
name: promote
description: Run the memory-promotion executor now - apply queued high-confidence promotions from a daily capture sweep into their governance/context/docs homes per governance/memory-promotion.md, with a fail-closed confidentiality scan and one commit per promotion. Use when the owner says promote, run promotion, apply the memory queue, or promote my lessons now. Ships dormant: the executor script is not included, see README.md in this folder before invoking. The manual override runs on the same code path as the daily job; the daily job is the default once wired.
---

# promote

Manual override for the autonomous memory-promotion job described in `governance/memory-promotion.md`.

**Ships dormant.** This skill has no executor yet: a `scripts/promote_memory.py` is not included in this skeleton. Read `skills/promote/README.md` first; it explains what the executor would do and what wiring it takes. Until you build or port one, promote lessons and facts by hand using the routing rule in `governance/memory-promotion.md`.

Once an executor exists at that path, the flow is:

1. Run `python3 scripts/promote_memory.py --now`.
2. It applies each high-confidence queued promotion per the routing rule, scanning fail-closed for confidential and secret content before commit; a hit is blocked and reported, never committed.
3. One git commit per promotion (commit-only, never push). Revert with `git revert HEAD`.
4. Low-confidence items stay queued for the weekly human touchpoint.
5. Report to the owner in one line: what promoted, what was blocked, what remains.
