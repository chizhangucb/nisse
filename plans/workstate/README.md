# workstate/

Live workstate files for multi-session tasks, one per task: `YYYY-MM-DD-<ticket-or-slug>.md` (a folder when a run has multiple artifacts). Each holds goal / done / in-flight / next / gotchas, updated at milestones so an unplanned session death costs minutes, not the whole thread (`governance/building.md`, continuous-checkpoint rule).

Lifecycle: rides the task, deleted when the task lands; a dirty tree with a stale workstate is an orphaned task and should be flagged. Agent-agnostic: any harness writes, any reads.
