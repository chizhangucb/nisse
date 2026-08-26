# records/

Four append-only streams ONLY. Anything else in this folder is a hygiene violation. These files are the system's memory; they never get rewritten, only appended.

The two structured ledgers are append-only JSONL. They are written ONLY through `scripts/aios_ledger.py` (a single serialized writer under a lock), and a deny hook (`.claude/hooks/ledger-guard.py`) blocks a raw Edit/Write or shell-redirect of them:

- `decisions.jsonl`: one JSON row per decision block that meets the logging bar, with its why. Row shape `{date, title, session, stream, body}`, stored oldest-first (newest at the bottom). Append with:

      python3 scripts/aios_ledger.py append-decision --date YYYY-MM-DD \
          --title '...' --session <this session id> --stream <name> \
          --body '- **Decision.** why. -> pointer'

- `sessions.jsonl`: one row per assistant session (an upsert store, refreshed each turn by the Stop hook). Row shape `{stamp, session, focus, repo}`, stored oldest-first; newest-first is a read-time view. Append/refresh with `python3 scripts/aios_ledger.py upsert-session --session ... --stamp ... --repo ...`.
- `brainstorms/`: interview-style discovery notes, one file per session, checkpointed as you go.
- `reports/`: recurring generated output (weekly digests, sweep reports).

**Logging bar, log iff:** (1) changes future behavior (policy/structure/schema/rule), (2) commits something hard to undo, or (3) settles a question a future session would re-litigate. Never logged: task completions, preferences already in rules, one-off no-recurrence choices. Body style: bold lead is the decision, then a short why, then a `-> pointer` to the source; aim ~30 words per bullet; no em dashes. One session = one block, keyed by session, scoped by stream.

Why append-only JSONL: the single locked writer removes the concurrent-rewrite corruption that plagued the old markdown tables, keeps the streams greppable and machine-readable, and a bad-line-tolerant reader survives a stray hand-edit. The former markdown mirrors (`decisions.md`, `sessions_index.md`, `log.md`) were removed once the JSONL covered them; they are recoverable from git history. Your history stays trustworthy forever.
