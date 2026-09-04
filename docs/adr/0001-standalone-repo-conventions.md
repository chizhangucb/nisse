---
status: accepted
date: 2026-09-03
---

# Adopt standalone-repo conventions and retire the governance machinery

nisse shipped as a copy of a private personal repo that had grown into a hub: 15 governance docs, JSONL ledgers with a deny hook, session hooks, a hygiene checker, dormant egress and routing machinery, and a satellite model for other repos. The upstream repo tore all of that down (its ADR-0001, 2026-09-02) after finding that standards without guards decayed into agent memory and nobody could tell which parts still did anything. We decided nisse follows: a short `AGENTS.md` map, a `CONTEXT.md` glossary, ADRs, GitHub issues as the tracker, skills for judgment, scripts for mechanics, and everything without a guard or an incident behind it deleted rather than rewritten.

## Considered options

- **Keep the governance layer as the kit's selling point.** Rejected: it was the exact machinery upstream could not tell was working. Shipping it to strangers is worse than running it.
- **Conventions without deletions.** Rejected: retired folders keep surfacing in grep and agent context, and a rewritten standard decays the same way the first one did.
- **Make nisse the upstream and have the private instance consume it.** Rejected: real usage happens in the private instance, so that is where shape gets tested. nisse is a hand extraction that lags on purpose; nothing syncs them.

## Consequences

- Two terms replace the enforcement vocabulary: a **standard** is a documented convention, a **guard** is a hook or test that fails when a standard is violated (see `CONTEXT.md`).
- Guards kept: a pre-push secret scan on public-remote repos that also fails on a pushed `CONFIDENTIAL` marker, a hook blocking destructive git commands, and one repo-shape test. Nothing else runs behind a session.
- Confidential folders carry a `CONFIDENTIAL` marker file; `docs/confidentiality.md` names the standard, never the paths.
- `CLAUDE.md` is a relative symlink to `AGENTS.md` wherever both exist. Windows clones need symlinks enabled in git; no repair script ships.
- The wiki loop is the product and the conventions are the frame. The wiki keeps its own page model (ADR-0002).
- Matt Pocock's engineering skills are the recommended process layer on any harness; nisse vendors none of them.
