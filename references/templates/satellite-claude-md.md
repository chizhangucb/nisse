# Satellite CLAUDE.md Template

Instantiate this file as a satellite repo's `CLAUDE.md`. Replace every `<placeholder>`; drop nothing without a reason. Canonical rules: `governance/satellite-repos.md` (boundary, records, push) and `governance/repo-contract.md` (file layout + always-loaded floor) in the hub; the hub files win on conflict. This block is the compact floor; it points, it does not mirror.

---

# <Repo Name>

<One-line role.> Satellite of the hub; owning project: `projects/<name>/` in the hub. Canonical pattern rules: `<hub path>/governance/satellite-repos.md`. Binding per-repo contract: `<hub path>/governance/repo-contract.md`. Registry row: `<hub path>/operations.md` `## Satellites`.

This file is a map: `<=~1,200 words`, each line pointing at a source of truth, nothing restated (`repo-contract.md`).

## Hub link

- Hub path comes from `AIOS_HUB` (default `<default hub path>`). Runtime code reads the hub read-only. No absolute machine paths in tracked files (path-relative + git-cloneable).
- `AGENTS.md` is `CLAUDE.md`'s twin: same content via symlink so any harness reads the floor.
- Confidentiality floor: nothing confidential (hub `wiki/confidential/` or any folder named in `confidentiality.md`) ever lands in this repo's files, fixtures, commits, or pushes. Fixtures are always synthetic, never copies of hub files. Sessions may read anything in the hub.

## Floor: hub governance pointers

The always-loaded floor is 3-5 never-violate rules (above) plus this pointer table; governance bodies load on demand, never all at once.

| Topic | Source of truth |
|---|---|
| Repo layout + floor | `<hub path>/governance/repo-contract.md` |
| Satellite boundary, records, push | `<hub path>/governance/satellite-repos.md` |
| Confidentiality (never leaves) | `<hub path>/governance/confidentiality.md` |
| Ticket lifecycle (all repos) | `<hub path>/governance/ticket-tracker.md` |
| Writing for the owner | `<hub path>/governance/communication-style.md` |
| Skill authoring + budgets | `<hub path>/governance/skill-authoring.md` |

## Records seam

- No `records/` in this repo. Decisions, brainstorms, and the session ledger live in the hub only; seam and hook wiring: `<hub path>/governance/satellite-repos.md`. Repo column in the ledger = `<repo name>`. The session-close sweeper fills focus lines after the session; do not fill them manually.

## Folder placement

- `docs/` holds user-facing published content ONLY. Internal knowledge (designs, handoffs, scratch) lives in the hub under `projects/<name>/`, fail-closed when publishability is unclear.
- `plans/workstate/YYYY-MM-DD-<ticket-or-slug>.md`: live per-task workstate; rides the feature branch, deleted at merge; confidential-task workstate stays hub-only.
- `.claude/` is harness machinery only (settings, hooks). Knowledge docs move to `docs/` if publishable, else the hub project folder.
- `graphify-out`, if graphs are wired, is always a symlink into hub `graphs/`, never a real directory.
- The hub's hygiene checker enforces all of the above across every registered satellite.

## Working rules

- Plan-first for anything non-trivial; the plan gets a yes before build.
- Style per `<hub path>/governance/communication-style.md`, files included.
- Commits free as work completes; push per `<hub path>/governance/gating.md` row 8.

## Pre-push scan list

Before any push, verify:
- No real hub documents or data in fixtures or tests (synthetic only).
- No absolute hub paths in tracked files.
- Nothing from `wiki/confidential/` or any folder named in `confidentiality.md`.
- <repo-specific items, e.g. gitignored projection files stay untracked>

## Repo specifics

<Free-form: run commands, architecture pointers, job definitions, visibility status as the owner confirmed it, quirks.>
