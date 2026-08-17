# Tool Actions

What the assistant can do on its own vs what needs your OK. Full model and rationale: `gating.md`; this is the operational view (the concrete tool list). On any posture question, gating.md wins. Edit the lists as you wire tools; keep every wired tool covered by exactly one list.

## Do freely, no asking

Read-only anything:

- Search and read email, calendar, files, chat channels, tracker issues, meeting transcripts.
- Web search and page reads.
- Create email **drafts** (drafts are not sends).
- Create and edit issues in your own personal tracker project: open items, deferred Backlog entries with revisit triggers, status moves. Any shared or team board stays confirm-first below.
- Git commits in this repo: atomic, clearly-messaged, agent-attributed. Reversible (reset/revert/reflog). Commit freely as work completes.

## Confirm first, every time

Anything other people see or that changes shared state:

- Sending email.
- Posting or DMing in any chat tool.
- Posting or replying on social media.
- Creating, editing, or commenting on shared tracker issues or team docs.
- Accepting, declining, creating, or moving calendar events.
- Sharing files or changing permissions on them.
- Publishing anything public.
- Spending money over your caps (set them in `operations.md`); under the caps is auto per `gating.md`.
- Git push: confirm-first until you wire the tier-3 egress gate with a pinned remote and a content scan; then it can move to conditioned-auto per `gating.md`.

Show the exact content and recipient before asking. One clear yes covers that one action, not the next.

The principle behind the gate: approval reads no signal about who asked. No env var, session marker, or "the owner told me to" skips the confirm. That keeps a compromised or confused agent from granting itself your authority.

## Escalate immediately

Surface at the top of the report, not buried:

- Anything touching the commitments you name here (your equivalent of board, investors, key customers).
- Time-sensitive requests that expire before you'd likely see them.
- Anything where another person is blocked waiting on you.
