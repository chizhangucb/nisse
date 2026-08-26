# records/

Four append-only streams ONLY. Anything else in this folder is a hygiene violation. These files are the system's memory; they never get rewritten, only appended.

The two structured ledgers are append-only JSONL. They are written ONLY through `scripts/aios_ledger.py` (a single serialized writer under a lock), and a deny hook (`.claude/hooks/ledger-guard.py`) blocks a raw Edit/Write or shell-redirect of them:

- `decisions.jsonl`: one JSON row per decision block that meets the logging bar, with its why. Append with `python3 scripts/aios_ledger.py append-decision --date ... --title ... --session ... --stream ... --body '- **Decision.** why. -> pointer'`. The bar and format live in `decisions.md`'s header.
- `sessions.jsonl`: one row per assistant session (an upsert store, refreshed each turn by the Stop hook). Append/refresh with `python3 scripts/aios_ledger.py upsert-session --session ... --stamp ... --repo ...`.
- `decisions.md` / `sessions_index.md`: the retired human-readable mirrors, kept through the migration bake; do not hand-edit them.
- `brainstorms/`: interview-style discovery notes, one file per session, checkpointed as you go.
- `reports/`: recurring generated output (weekly digests, sweep reports).

Why append-only JSONL: the single locked writer removes the concurrent-rewrite corruption that plagued the old markdown tables, keeps the streams greppable and machine-readable, and a bad-line-tolerant reader survives a stray hand-edit. Your history stays trustworthy forever.
