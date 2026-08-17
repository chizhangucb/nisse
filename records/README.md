# records/

Four append-only streams ONLY. Anything else in this folder is a hygiene violation. These files are the system's memory; they never get rewritten, only appended (and rotated to `decisions_history/` at the word cap).

- `decisions.md`: every decision that meets the logging bar, with its why. Newest first. Format and bar in its header.
- `sessions_index.md`: one row per assistant session, hook-maintained. Newest first.
- `brainstorms/`: interview-style discovery notes, one file per session, checkpointed as you go.
- `reports/`: recurring generated output (weekly digests, sweep reports).

Why append-only: your history is the most valuable thing this system accumulates. Mutable history rots; an append-only stream stays greppable and trustworthy forever.
