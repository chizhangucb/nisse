# nisse product contract

Status: living · Owner: the kit maintainer · Location: `spec/product-contract.md` (public, Apache-2.0)

## Purpose
nisse is a starter kit for a personal AI operating system: a plain-files git repo an agent lives in, shipping the folder taxonomy, written governance, append-only records, and knowledge loops. It is the public skeleton of a private instance, extracted so a stranger's first clone works; the shape ships, none of the maintainer's data does.

## Surfaces
The interfaces a user or agent consumes. One line each.
- `python3 scripts/setup.py`: idempotent first run: toolchain check, floor-symlink repair, name personalization, `.env` scaffold. Never touches your content.
- The floor: `AIOS.md` (root map; `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` symlink it) plus `governance/*`, the rules an agent loads every session.
- Wiki loop skills: `/wiki-ingest`, `/wiki-distill`, `/wiki-triage` (plus `/grill-me`, `/handoff`); host-agent only, zero keys.
- Hooks + hygiene: session-ledger and session-close hooks keep `records/` written; `scripts/hygiene_check.py` (`/hygiene`) checks structure and freshness.
- Connectors (tier 2, bring your own keys): Fireflies, Plaud, AssemblyAI (`/wiki-retranscribe`), Linear; enumerated in `.env.example` and the `operations.md` Connectors table.
- Dormant seams (tier 3): egress gate, model routing, graphs, spoke pattern, memory promotion (`/promote`); each README is its own wiring guide.
- Installable-job example: `scripts/daily_maintenance.py` (dormant; template in `scripts/templates/`), copied and scheduled by the user, never pre-installed.

## Owned data
nisse is the source of truth for the public skeleton: taxonomy, governance templates, skills, hooks, hygiene checker. It owns no user data; every clone's own `context/`, `records/`, `wiki/`, and `.env` belong to that instance, and nisse never writes them.

## Consumers
A person cloning the kit and the coding harness they run it in (Claude Code is first-class; any `AGENTS.md` reader works). Sibling local-first tools read a nisse-shaped repo: Chronicle (session depth) and Varde (operator console) consume its structure; neither is consumed by it.

## Non-goals
Not an app, service, framework, or library: no runtime, no server, no account, no telemetry, no outbound calls. Ships no private data, keys, or history. Does not manage or update your instance after clone; setup never edits your governance or content.

## Invariants
OWNER SIGN-OFF TO EDIT. These are the confidential-to-public pipe rules.
- Build by addition: every file is written fresh or rewritten from one named private source, never bulk-copied; provenance is tracked one row per file.
- Two scrub gates before anything lands: a denylist scanner (names, secrets, machine paths, private-knowledge slugs) and an independent model-review pass.
- The maintainer reviews the final public text; nothing lands without it.
- Clean git root: no pre-scrub blobs or commit messages ship.
- No private-instance name, person, path, secret, or knowledge slug ever ships; the only exceptions are deliberate, ratified, and whitelisted (attribution, the public clone URL).

## Change triggers
Update this file in the same pass when one fires: a new private-instance capability extracted into the kit; a new connector, skill, or hook ported; a new ratified whitelist exception; a change to the scrub-gate practice or the provenance ledger.

## Pointers
In-repo: `README.md` (front door), `AIOS.md` (the map), `governance/README.md` (the rules), the tier-3 READMEs for the dormant seams. The provenance ledger and scrub tooling live in the private instance, not here.

## Roadmap
Only Now is a commitment.
- Now: this contract, and keeping the tier-1 clone-and-go loop clean through the scrub gates.
- Next: more connectors and skills ported as each clears the gates.
- Later: broader harness coverage beyond Claude Code; wider reuse of the skeleton.
