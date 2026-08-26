# Decisions

Append-only record of decisions and why. Newest block at the TOP.

The live store is `records/decisions.jsonl` (one JSON row per decision block: `{date, title, session, stream, body}`), written only through the sanctioned command:

    python3 scripts/aios_ledger.py append-decision --date YYYY-MM-DD --title '...' --session <id> --stream <name> --body '- **Decision.** why. -> pointer'

The deny hook (`.claude/hooks/ledger-guard.py`) blocks a raw Edit/Write or shell-redirect of the ledger, so appends stay serialized, append-only, and validated. This markdown file is the retired, human-readable mirror kept through the migration bake; do not hand-edit it.

**Logging bar, log iff:** (1) changes future behavior (policy/structure/schema/rule), (2) commits something hard to undo, or (3) settles a question a future session would re-litigate. Never logged: task completions, preferences already in rules, one-off no-recurrence choices.

**Format:** one `## YYYY-MM-DD: Title` header (append `(session <id>, stream: <name>)`; hooks and pipelines parse these, so never alter them), then one bullet per decision: `- **Decision stated.** Why clause. → pointer`. Bold lead is the decision, then a short why, then a pointer to the source with the long story (brainstorm Q#, plan doc, file path). Aim ~30 words per line; push detail to the pointer, never truncate meaning. A block with multiple decisions gets multiple bullets. Written in-flow by the deciding session, never deferred.

---

<!-- log-shards -->
Rotated history:
(none yet; rotated months land in decisions_history/)
<!-- /log-shards -->

## 2026-08-24: nisse CI/PR posture — CI, confidentiality guard, PR flow, branch protection (session 36bc19ca, stream: hub)

- **nisse moves to a PR-only flow: direct push to `main` is closed by branch protection (enforce_admins, required checks `test`/`lint`/`confidentiality`, PR required with 0 approvals, no force-push), mirroring chronicle.** Gives the hub the same server-side merge gate its satellites have. → plans/2026-08-24-chi-219-ci-pr-posture.md; CHI-219.
- **CI is three required jobs on push+PR to `main`: pytest, ruff (scoped to `scripts/`, `.claude/` excluded), and a confidentiality guard.** Deterministic gate before merge; ruff config in `pyproject.toml`. → CHI-219.
- **The confidentiality guard flags only absolute owner home paths (a `/Users/` or `/home/` prefix immediately followed by the username), never the bare public handle, and self-excludes the guard, its test, and plan/archive docs.** A naive prefix+username denylist false-positives on the public handle and the guard's own artifacts. → scripts/confidentiality_guard.py; CHI-219.
- **`gh pr merge` is owned by GitHub branch protection, not the egress gate — the gate passes it through to the raw command.** Confirms the branch-protection-owns-merge posture; supersedes the CHI-229 catch-all reading. Push to `main` stays conditioned-auto against the nisse pin; tag/non-main refs card. → CHI-229; scripts/gating_policy.json push_pins.
