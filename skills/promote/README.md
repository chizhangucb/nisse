# Memory-promotion executor (tier 3, ships dormant)

Wiring guide for the executor behind the `/promote` skill and the optional daily promotion job in `governance/memory-promotion.md`. Nothing runs until you write or port a `scripts/promote_memory.py`; the skill and the policy file are ready, the executor is not shipped.

## What it would do

- Read a pending-promotions queue (e.g. a `.tmp/daily_sweep/pending_promotions.json` written by a daily classify-and-queue step) and apply each HIGH-confidence entry to its routed home (`governance/`, `context/`, or a project `docs/` lesson file) per the routing rule in `governance/memory-promotion.md`.
- Run the confidentiality and secrets scan on every promotion before writing, fail-closed: a tripped item is blocked and reported, never committed.
- Make one git commit per promotion, so the audit trail is native `git log` and the undo is `git revert HEAD`.
- Leave LOW-confidence items in the queue for a weekly human pass instead of auto-applying them.

## Wiring it up

1. Decide the capture-to-queue step first: what classifies a changed memory file as promotable, and where the queue file lives. This can be a small deterministic script; detect-and-queue needs no model.
2. Write `scripts/promote_memory.py` to read that queue, apply the routing rule, run the scan, and commit. Model posture and cadence are in `governance/memory-promotion.md`.
3. Wire the daily run as a scheduled task in `operations.md`, and point the `/promote` skill's manual-override step at the same script.
4. Add the queue file and the executor script to your egress and confidentiality review the same pass you wire it: it's an unattended writer.

Until this is built, the routing rule in `governance/memory-promotion.md` is still useful by hand: when you or your assistant notice a durable lesson, route it there yourself.
