---
name: handoff
description: Compact the current task into its in-repo workstate file so another agent (any model, any harness, any machine) can resume fast. Use whenever the owner says hand this off, handoff, write a handoff, I'm switching models/agents, running low on credits or context, or pausing this to continue later. Not for landing handed-over files (wiki-ingest), not the always-on milestone checkpoint (that is the continuous-workstate rule in governance/building.md), not a transcript dump.
---

## What this skill does

Writes the current task's state into its workstate file so the next agent picks it up in minutes, not by re-reading a transcript. This is the PLANNED-switch companion to the always-on continuous-workstate rule in `governance/building.md`: that rule keeps the file fresh at every milestone; `/handoff` is the deliberate "I am stopping now, capture everything" pass before a model, harness, or machine switch.

Task-level state, never transcript conversion. The output is plain markdown any harness can write and read.

## Where it writes

One file per task: `plans/workstate/YYYY-MM-DD-<ticket-or-slug>.md` in the task's own repo. Shape, lifecycle, and the confidential-tasks-hub-only rule live in `plans/workstate/README.md`; read it, do not restate it. If the task already has a workstate file, update it in place (keep its date and first-seen); else create it dated today.

## Steps

1. Identify the task and resolve its workstate path (existing file, else new dated one).
2. Fill the five sections from the conversation: goal / done / in-flight / next / gotchas. Be concrete and short.
3. Reference artifacts by path, never paste their contents (link the plan doc, the branch, the ticket, the key files). Duplication rots.
4. Add a "suggested next steps" list for the next agent and a short "read these first" pointer list (the 2 to 4 files or the ticket it should open before touching anything).
5. Redact secrets: no keys, tokens, `.env` values, or confidential-tree content in the file. If the task is confidential, the workstate stays hub-only.
6. Confirm the written path back to the owner in one line.

## Boundary

| This skill IS | This skill is NOT |
|---|---|
| An explicit, on-demand compaction to the workstate file before a switch or pause | The always-on milestone checkpoint (that is `building.md`, done every milestone without asking) |
| Task state (goal/done/next), artifacts by reference | A transcript dump or a summary of the whole chat |
| In-repo plain markdown, agent-agnostic | Saved to an OS temp dir, or tied to one harness |

Not `/wiki-ingest` (that lands sources into the wiki) and not a `records/decisions.md` write (decisions still get logged in-flow).
