# Wiki Log

Append-only chronology of wiki operations: one dated line per ingest, distill batch, triage pass, or structural change.

The live store is `wiki/metadata/log.jsonl` (one JSON row per operation: `{date, op, detail}`), written only through the sanctioned command:

    python3 scripts/aios_ledger.py append-log --date YYYY-MM-DD --op <op> --detail "<detail>"

The deny hook (`.claude/hooks/ledger-guard.py`) blocks a raw Edit/Write or shell-redirect of the ledger, so appends stay serialized and append-only. This markdown file is the retired, human-readable mirror kept through the migration bake; do not hand-edit it.

(Your first ingest will land here in the jsonl. Old line format was: YYYY-MM-DD | op | detail.)
