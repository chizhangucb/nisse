# Operations

How this AIOS reaches the world and what runs unattended: connections, scheduled tasks, budgets and escalation. The hygiene checker reads this file for coverage and freshness. Registries here are canonical: wiring or retiring anything means updating the matching table in the same pass.

## Connections

Every system the assistant can reach, one row each. Start empty; add a row the day you wire a tool.

| # | Domain | Tool | Mechanism | Auth | Last checked |
|---|---|---|---|---|---|
| 1 | (example) Meeting intelligence | Fireflies | key+ref (`.env`) | API key | never |

**Mechanism options:** `mcp` (MCP server), `script` (Python/Bash hitting an API, in `scripts/`), `export` (CSV/JSON dump pipeline), `key+ref` (`.env` key + `references/<tool>-api.md` guide), `not yet connected`. When you wire a new tool, save `references/<tool>-api.md` (endpoints, auth flow, common queries): researched once, saved forever.

## Connectors

The canonical human-readable list of optional integrations (tier 2). Each bolts onto a working tier-1 loop; nothing here is required. Env vars live in your gitignored `.env`; the tracked `.env.example` enumerates them with comments; storage rules in `governance/secrets.md`.

| Connector | Unlocks | Env var | Setup |
|---|---|---|---|
| Fireflies | pull meeting transcripts straight into wiki ingest | `FIREFLIES_API_KEY` | key from fireflies.ai settings; test with the wiki-ingest skill |
| Plaud | pull voice-capture notes into wiki ingest | (MCP auth) | connect the Plaud MCP in your harness config |
| AssemblyAI | re-transcribe garbled captures | `ASSEMBLYAI_API_KEY` | key from assemblyai.com; used by the retranscribe script |
| Linear | daily ticket-tracker drift sweep (`governance/ticket-tracker.md`) | `LINEAR_API_KEY` | personal API key, user scope; enable the sweep in the hygiene config |

## Scheduled tasks

The single registry of everything that runs unattended. Adding, changing, or retiring a job means updating this table in the same pass. Nothing ships pre-scheduled; rows appear as you install jobs.

| Job | Schedule | Max staleness | Runner | Last run | What it does |
|---|---|---|---|---|---|

**Drift principle:** each job should stamp a heartbeat; a daily check flags any job over its staleness threshold. Silence from a job that reports daily means the job broke, not that all is well.

**Cadence tiers:** event-driven writers (hooks), daily detectors (cheap deterministic sweeps that surface what needs a human), weekly deep-clean. A detector detects and queues; it never does the sensitive mutation. Keep detectors LLM-free so they run unattended; judgment stays where a model and your yes both exist.

## Satellites

Registry of repos outside this hub that touch it (definition and rules: `governance/satellite-repos.md`). Canonical and machine-parsed (hooks and hygiene read it). A repo becoming a satellite gets its row in the same pass; retired rows move to an archive note.

| Satellite | Repo path | Remote | Project | Hub access | Jobs | Visibility |
|---|---|---|---|---|---|---|

## Budgets and escalation

Skeleton; set your own numbers and keep them honest.

- **Per-task spend cap:** e.g. $0.50 per transcription. Above it, find a cheaper route or ask before spending.
- **Unattended-run kill switch:** a notional cap per scheduled run as a runaway-loop backstop; over cap = abort remaining stages and escalate.
- **Escalations batch:** full text in `records/reports/`, a short ping to wherever you read notifications. More than a handful of escalations a week is a pipeline defect, not workload.
- **Model routing:** route judgment-heavy work to your strong model, script-checkable work to cheap ones. Policy: `governance/routing.md` (dormant until you wire a router).
