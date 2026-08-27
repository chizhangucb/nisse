# Satellite Repos

How code repos outside the hub relate to it. Canonical page; satellites reference it by path.

## What a satellite is

A satellite is any repo outside the hub that touches it: reads hub data, runs a registered job against it, or implements a function of this operating system. Status, not location; any project's repo can cross the line the day it starts reading the hub. Non-satellite repos are listed in their project folder only.

## Two-axis model

Project = unit of intent; its hub folder (`projects/<name>/`) is the memory home and lists its repos (path, remote, one-line role). Repo = unit of code, always outside the hub. Code never lives in hub folders.

## Boundary invariants

- Satellite runtime code reads the hub read-only.
- Agent sessions may write exactly two hub surfaces, by absolute path: `records/` (the 4 streams) and `plans/workstate/` (live per-task workstate; hub-only for every satellite, never satellite-local, `repo-contract.md` "One memory home per project").
- No cross-boundary imports, either direction. CLI invocation of read-only hub tools is allowed.
- Helpers duplicate freely; extract to a versioned package only after double-fix pain.
- Confidential: sessions read anything; nothing confidential lands in satellite files, fixtures, or commits. Runtime inclusion of confidential paths is per-satellite, owner-approved, via a separate gitignored projection, loud when on.

## Records seam

Decisions append to the hub `records/decisions.jsonl` via `scripts/aios_ledger.py append-decision` (one block per session+stream, `--stream <name>`), logged in-flow; brainstorms to hub `records/brainstorms/`. Session rows in `records/sessions.jsonl` are written by the Stop hook; the `repo` field = satellite repo name, hub sessions write `hub`.

Do not fill `(pending)` focus lines manually; the session-close sweeper owns that.

Hook registration template: every satellite carries the hub's hook block in its tracked `.claude/settings.json` (one template, no per-repo drift; hub path resolves via `AIOS_HUB`). The template ships with the hooks in this repo's `.claude/`.

Split trigger: hygiene flags a records file at ~10k words; you approve; split per-stream, consistent across files, history migrated.

## Session routing

cwd = where the files you'll edit live. Satellite code work opens at the satellite cwd; trivial cross-repo touches from either side are fine.

## Push

Commits free; push per `gating.md` row 8, with a per-satellite scan list in its CLAUDE.md. Remote guardrails inherit `confidentiality.md`. Visibility (public/private) is case-by-case, stated per satellite in the registry, never pre-assumed.

## Renames

Renaming or moving any hub path a satellite might read (packages, data dirs, CLIs, state roots): grep every registered satellite for the old names before calling the rename done. Hub-only greps miss satellite readers.

## Registry

`operations.md` `## Satellites` (canonical, machine-parsed; row added the same pass a repo becomes a satellite). Floor template: `references/templates/satellite-claude-md.md`. Binding per-repo layout contract: `governance/repo-contract.md`.

## Tracker

Follows the project axis. A satellite gets its own tracker project when its roadmap decouples from the hub's; an OSS release is the canonical decoupling event.
