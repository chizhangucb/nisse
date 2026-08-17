# Batch-run playbook

Operational knowledge for multi-ticket agent runs, distilled from real runs of the system this was extracted from. Read before authoring any batch. Binding rules live in `governance/` (building.md Landing + Decision queue sections, ticket-tracker.md); this file is the craft around them.

## Right-size the vehicle

- Single-step task (status flip, comment, one-file edit, a decision already made): do it inline, seconds, zero agents. Never wrap a 30-second action in an orchestration.
- Small code change in a low-risk file: one maker agent, one review round, land.
- Code that can break a live system or a security surface (the egress gate, scheduled jobs, the wiki pipeline): full loop. Maker, fresh-context adversarial review, cap 3 rounds, serialized landing, strict smoke on landed main. This loop costs 3-5x naive execution and is worth it exactly there, nowhere else.
- A workflow orchestration pays only for parallel bulk (10+ independent items). Its overhead: watcher cycles, resume complexity, host-process death risk.

## Four lanes, four done-conditions

Build (In Review with landed smoke) / plan-first (draft staged, build on lock) / trigger-check (evidence appended to the ticket description, status unchanged) / decision-card (queue item, follow-through on lock). Classify the pool before sizing the run; most Backlog tickets are not builds.

## Workflow mechanics that bite

- Idle agents get culled after a few silent minutes: any wait must loop short sleeps with output between.
- Workflows die silently with the host process. Long runs need an external liveness check (wakeup, cron, or a human glance); never assume a quiet run is a running run.
- Resume replays cached results and re-runs in-flight agents: side-effectful agents (landings, notifications, tracker writes) must check current state before acting, or a resume sends duplicates.
- One poll agent covering all watched tickets per cycle, never one per ticket.
- Notification smokes fire real pings unless the notify path is stubbed too; executor stubs alone are not enough.
- The permission layer blocks autonomous production actions (service restarts, merges into live-serving files) unless the owner pre-named them. Design those steps as staged-plus-one-command-for-the-owner from the start instead of discovering the block mid-run.

## Review discipline

- Deterministic gates (tests, hygiene) before any model review; no review tokens on red code.
- A doc sentence claiming more safety than the code has is a landing blocker, same severity as a code defect. State residuals, never deny them.
- A decision card's framing is verified at execution time: stale premise or hidden scope pauses the item and re-presents it (building.md, Decision queue).

## Cost shape

- Checkers, cards, polls, bookkeeping: a cheap model at low effort. Makers: your strong model. Reviewers: your strong model at high effort. Never a frontier model on mechanics.
- A full-day batch can consume most of a subscription window. Check remaining headroom before launching a run sized like that; a run that outlives the window dies mid-flight.

## Completion

- A run is complete from the BOARD's perspective, not the workflow's: sweep every owner comment before the word "complete".
- End with one decision queue, never N tickets to walk.
