# Repo Contract

The per-repo shape this hub and every registered satellite must hold. Complements `satellite-repos.md` (boundary, records seam, push rules live there and win on conflict); this file adds the file-layout, folder-lifecycle, and always-loaded-floor contract.

## The floor file is a map

- The always-loaded floor (hub: `AIOS.md`; satellites: `CLAUDE.md`) is a map, not a manual: `<=~1,200 words`, each line pointing at a source of truth, nothing restated.
- `.claude/` holds harness machinery ONLY: settings, hooks, worktrees. Knowledge (design rubrics, product contracts, dev notes) is not machinery.
- Knowledge moves to a repo's `docs/` if publishable, else to the hub project folder. Public-repo fail-closed: when publishability is unclear, it goes to the hub, per `confidentiality.md`.

## Thin always-loaded floor

- CLAUDE.md and AGENTS.md carry the SAME content, via symlink (preferred) or generation, so any harness reads the same floor. The hub's real file is `AIOS.md`, with `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` symlinked to it.
- A satellite's floor is small: 3-5 never-violate rules plus a pointer table into the hub's `governance/`. Governance bodies load on demand, never all at once.
- Required floor pointers (hygiene-enforced): the table must carry rows for `repo-contract.md`, `satellite-repos.md`, `confidentiality.md`, `ticket-tracker.md`, `communication-style.md`, `skill-authoring.md`, `secrets.md` (credentials), `building.md` (plan/land discipline), `tool-actions.md` (auto/confirm/escalate table), and `gating.md` (the immovable floors). A floor missing any is a finding.
- No-orphan floor guarantee: every `governance/*.md` is EITHER a required floor pointer above OR on the documented exclusion list, never neither. Transitive reference does not count: a load-bearing doc only reliably loads as a floor row. `scripts/hygiene_check.py` fails HIGH on any unclassified governance doc, so a rule can never silently fall out of the floor. On-demand / owned-elsewhere exclusions today: `routing.md` (metered model-routing only; the harness's own model needs no router), `design-rubric.md` (on-demand UI rubric), `lessons.md` (on-demand catch-all), `memory-promotion.md` (loaded by the promotion pipeline when it runs). Exclusion turns on load-bearing-ness, not dormancy: a dormant-until-wired doc that is still an obligation (e.g. `ticket-tracker.md`) stays required. `README.md` is the folder index, not a rule doc, so it is neither.
- Floor and pointers are path-relative and git-cloneable; no absolute machine paths in tracked files. The hub path resolves via the `AIOS_HUB` env var.

## Product-repo layout (satellites)

- Top-level directories come from a fixed vocabulary, exact names, no plural variants: `src/`, `server/`, `shared/`, `scripts/`, `test/`, `spec/`, `docs/`, `dist*/`. No `tests/`, `specs/`, `srcs/`.
- Extra runtime components are allowed only when named in that repo's CLAUDE.md.
- `docs/` in a product repo is user-facing published content ONLY. Internal knowledge (designs, handoffs, scratch) lives in the hub's `projects/<name>/` folder, fail-closed.
- Root markdown allowlist: `README`, `CHANGELOG`, `LICENSE`, `NOTICE`, `CLAUDE.md`, `AGENTS.md`. Anything else at the root is a finding.
- All tests live in top-level `test/` (unit and e2e together). No `__tests__/` dirs or `*.test.*` files scattered under `src/`.

## Hub layout

The hub is not a product repo: it keeps `scripts/tests/` and its own folder set. One row per root folder. Per-folder READMEs are part of the skeleton and always allowed.

| Folder | Holds | Lifecycle | Enforcer |
|---|---|---|---|
| `context/` | who the owner is: business, priorities, goals | live heading refreshed; goals frozen quarterly | hygiene freshness |
| `records/` | the 4 append-only streams only | append-only, immortal; rotate at word cap | hygiene taxonomy |
| `plans/` | build docs (plans, designs, PRDs), dated `YYYY-MM-DD-<slug>` | mutable-mortal; archive to `archives/plans/` on ship | dated-name check |
| `scripts/` | pipeline mechanics; tests in `scripts/tests/` | promoted at 2+ consumers or a scheduled-job dep | review-first for gate code |
| `graphs/` | committed registry `index.json`; artifacts gitignored | registry tracked; artifacts rebuilt on schedule | graph runner |
| `wiki/` | the knowledge layer | per `wiki/CLAUDE.md` schema | wiki health + triage |
| `projects/` | workstream folders | per-project; index in its README | confidentiality |
| `skills/` | the skills; `.claude/skills` symlinks here | per `skill-authoring.md`; edits auto + periodic diff review | hygiene budgets |
| `contacts/` | local contact store, one YAML per person | script-maintained | hygiene contacts |
| `references/` | actively-consulted lookups | no dating; archive candidate at mtime > 90d and zero repo references | hygiene staleness |
| `archives/` | retired material, mirror-path for reverse restores | immortal | hygiene structural |

- Hub root allowlist: `AIOS.md` + the `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` symlinks, `README.md`, `LICENSE`, `NOTICE`, `operations.md`, `.env.example`. Growing the root is a contract change, not a convenience.

## Archive lifecycle

- The shipping session archives its plan doc in the same close-out (`plans/<x>` to `archives/plans/<x>`). Weekly hygiene is the backstop, proposing confirm-to-fix batches for shipped plans left behind.

## One memory home per project

- A satellite product's internal docs live in `projects/<name>/` in the hub. The hub's own memory home is the hub itself: `plans/` for build docs, `records/` for the streams.

## Citation rule

- Live code or governance may cite `plans/` only for in-flight work. A durable citation means the cited content gets PROMOTED to a persistent home (subsystem README, governance file, product doc), the citation repointed there, and the plan archives. Provenance-only citations point at the `archives/plans/` path directly, stable by the mirror-path rule.

## No satellite records; graphs stay in the hub

- No `records/` in a satellite. The 4 append-only streams live in the hub only (`satellite-repos.md` records seam).
- A satellite's `graphify-out` is always a symlink into hub `graphs/`, never a real directory.

## Enforcement

- `scripts/hygiene_check.py` reads the `operations.md` `## Satellites` registry and enforces this contract, the doc budgets, and `skill-authoring.md` across the hub and every registered repo.
