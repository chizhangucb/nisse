# Ticket tracker rules (all product-development boards)

Scope: every repo/project with a product-development lifecycle. The contract is tracker-agnostic (written against Linear-style boards); per-project mechanics (which board, which sweep) register in `operations.md`. Dormant until you wire a tracker; the wiki and records work fine without one.

The tracker is canonical for work state; `records/` for history and decisions. Updating the ticket is part of the work, same rank as committing.

## Status semantics

- **Backlog**: parked idea, not ready. May die freely.
- **Trigger-gated Backlog**: Backlog ticket whose description opens with `Revisit trigger: <condition>`. Not recommendable or claimable until the condition is verified true against current repo/records state, never from memory. Checking one is work: append the result (fired/not, evidence, date) to the description.
- **Todo**: claimable. Description is a complete brief a cold agent could execute: context, done-condition, pointers. Fails this bar, stays Backlog.
- **In Progress**: claimed, actively worked. Names its owner (session ID or agent). Stale after 7 quiet days; the sweep flags it.
- **In Review**: complete per the brief, evidence attached (commit hash and completion comment with session ID). Awaiting the owner. Never enter with unfinished children.
- **Done**: the owner only. Never set by an agent.
- **Canceled**: killed by an explicit decision, referenced in a closing comment. Stale-but-alive goes back to Backlog instead.

## Parent and sub-issue rules

- A ticket with sub-issues is a container; status is derived, never hand-set. All children unstarted, parent Todo; any child In Progress, parent In Progress; parent reaches In Review only when every child is In Review, Done, or Canceled. A parent with unstarted children is NEVER In Review (carving out children is not implementation).
- Sub-issue test: does this block the parent's completion? Blocking, sub-issue. Merely related, standalone plus a related-link or label.
- Parents are scoped deliverables, not themes. Phase-scale groupings become projects or milestones, not mega-tickets.

## Scope

- A started ticket's scope is frozen; new work found mid-flight is a new ticket.
- Checkboxes in the description are for subtasks of the existing scope only; anything with its own done-condition is its own ticket.

## Descriptions and comments

- The description is the single, current, self-contained brief. Editing it when scope or approach changes is part of the work. Comments never patch a stale body.
- Comments carry exactly two things: claim/handoff notes, and one completion note (what shipped, session ID) at In Review. Progress narration goes to `records/`, decisions to `records/decisions.md`.

## Enforcement

- Working sessions write content and state in-flow. The optional daily tracker-drift sweep (tier-2 connector, off by default) repairs state and flags content staleness; it never edits descriptions or comments.
- Sweep authority: auto-fix evidence-provable state flips only (commit-referenced Todo to In Progress; parent In Review with unstarted children back to In Progress). Propose-only: Canceled, Done, archive. More than 5 items waiting on the owner is a backpressure signal, reported loudly.
