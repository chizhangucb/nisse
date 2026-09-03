# Memory promotion

> **Tier 3, ships dormant.** The autonomous job described below does not run until you build or port an executor, and no manual-override skill ships with this repo. Until then, use the routing rule here by hand whenever you or your assistant notice something durable.

Owns the capture-to-promote pipeline: where captured memory comes from, where the next lesson goes, the promotion cadence, and how promotion targets stay clean. Governs promotion of captured memory only. The system's other promotions (wiki raw to truth, plan to archive, project lifecycle) keep their own homes.

## Capture surfaces (what you promote FROM)

- Per-project auto-memory, if your harness keeps one (a structured funnel of things it noticed).
- `records/` (decisions, brainstorms).
- Live sessions.
- A secondary agent's raw capture, if you run one (`references/spoke-pattern.md`), via whatever sync job mirrors it in. A spoke's own curated memory file is NOT slurped: importing another model's salience without the source is out of scope.

## Routing rule (where the NEXT lesson goes)

1. Preference about how the assistant works -> `governance/` (feedback) or the matching rule file.
2. Fact about you or the business -> `context/`.
3. Project-specific lesson -> product repo `docs/` (publishable) or hub `projects/<name>/` (fail-closed per `confidentiality.md`).
4. Cross-project lesson that fits a recurring domain -> that domain's governance file (`design-rubric.md` today; create a new domain file when a domain actually recurs).
5. Cross-project lesson, domain-less or too small for its own file -> `governance/lessons.md`.
6. (Deferred) A never-violate core also earns an always-loaded floor line.

Rules 4 and 5 route by what the reader DOES with the entry, not by where it came from: a behavioral rule the assistant must follow while working (a design floor, a coding convention) goes to `governance/`; a diagnostic runbook read when troubleshooting a symptom goes to `references/` instead, per that folder's own definition (lookup artifacts read to do work). Both may be promoted from the same capture; the split is by function, not by origin.

## Cadence (autonomous once wired, act-then-log)

Promotion is meant to be autonomous, not approval-gated, once an executor exists. Git is the audit trail and the undo.

- **Detect + queue (daily, deterministic, no model):** a daily sweep classifies changed memory files and queues promotions in a pending-promotions file.
- **Act (daily job, a capable mid-tier model):** reads the queue and auto-applies each promotion per the routing rule above. One git commit per promotion (the audit trail; one-command revert). Empty queue skips the model.
- **Report (FYI, not approval):** an exception-based notification through whatever surface you've wired (`operations.md`) when something moved: what moved, from where, and the revert command. Never blocks.

Two guardrails stay (automatic, safety not friction):

- **Confidentiality and secrets scan on every promotion, fail-closed.** A tripped item is hard-blocked and flagged for manual handling. An autonomous leak into a public-inherited file is unrecoverable.
- **Confidence tiering.** High-confidence -> auto-promote. Low-confidence -> held for a weekly human touchpoint.

## Promotion-target hygiene

Autonomous writes touch many files, so targets must be bounded and self-cleaning.

- **Write-target set (location-scoped):** any file under hub `governance/`, any project-repo `docs/` lesson file, and `context/`. Directory-scoped, so a future domain file is covered the moment it exists.
- **Per-file caps (mechanical):** `scripts/hygiene_check.py` caps every `governance/*` file and every project `docs/` lesson file. New files inherit the cap.
- **Write-time consolidation (the main defense):** when a promotion would push a file over cap, consolidate or retire in that file BEFORE writing. Every entry carries a provenance link.
- **Mechanical backstop (no model):** hygiene flags any target over budget, missing a provenance link, or structurally cruft.
- **Semantic backstop (a small model, weekly, incremental):** a triage-style pass over the target set flags duplication, contradiction, and superseded entries a word count cannot see. Content-hash gated, exception-based.

## Model posture

- Semantic hygiene detection: a small, cheap model (flags only, never mutates).
- Autonomous promotion (drafting and consolidating governance): a capable mid-tier model (unsupervised judgment a script cannot check; volume is tiny).
- Low-confidence items: a frontier-tier model, via the weekly triage.
