# Building

General build discipline. Binds every agent doing non-trivial build or research here, not just skill authors. Skill-specific craft: `skill-authoring.md`.

## Process

- Plan first. Non-trivial builds get a plan doc in `plans/`, reviewed and approved by you before any file is created. Never build then backfill the plan.
- Archive on ship. The shipping session archives its plan doc in the same close-out (`plans/<x>` to `archives/plans/<x>`); weekly hygiene is the backstop. Lifecycle: `repo-contract.md` (Archive lifecycle).
- Review-first is scoped to the enforcement machinery, not governance prose. Editing harness permission settings or hooks (the code that executes the gates) needs your explicit yes every time. Governance `.md` edits follow plan-first: when an approved plan covers the change, they're auto, protected by plan review plus the commit audit trail. Skill edits are auto (commit like code), backstopped by a periodic diff review.
- Continuous workstate: every multi-session or long task keeps a live file at `plans/workstate/YYYY-MM-DD-<ticket-or-slug>.md` (shape: `plans/workstate/README.md`), updated at each milestone, so an unplanned session death costs minutes, not the thread.

## Efficiency

- Every design or architecture proposal states run cost: how often it runs, rough tokens per run, which model. Default to the cheapest shape that meets the quality bar: deterministic code, then one-shot small model, then one-shot big model, then agentic session. Agentic plus a big model needs explicit justification in the plan.

## Validation

- Validate load-bearing technical claims (agent capabilities, model behavior, API terms, vendor data policies) against official or primary docs before relying on them. Third-party course, marketing, or secondhand claims are leads to verify, not facts.

## Landing to main

- Multi-commit git surgery (cherry-pick, rebase, merge, multi-commit reset) runs in a dedicated `git worktree` when other sessions may share the checkout; a concurrent branch switch silently redirects your commits.
- The working tree is yours only once proven: no unexplained uncommitted edits, HEAD where you left it. If HEAD moved on its own, stop and diagnose. Never `git reset --hard` or rewrite a branch another live session may hold uncommitted work on.

## Decision queue

Any session leaving 2+ open decisions for you emits ONE numbered list, never a walk through tickets. Each item capped at 5 lines: the question in one sentence, 2-3 options with one-line tradeoffs, a recommendation with rough cost, and a default-if-silent with an expiry. Nothing irreversible ever defaults on silence. You reply in shorthand ("1A, 2 yes, 5 skip"); the assistant fans out the follow-throughs and records each executed decision.

An approval executes against what the option ACTUALLY is, verified at execution time. If execution reveals the framing was wrong (stale premise, hidden scope), pause and re-present it amended; never execute the literal-but-wrong reading and never silently substitute.
