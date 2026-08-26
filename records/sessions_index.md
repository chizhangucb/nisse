# Session Index

Ledger of every session: one row each, newest first. The row is the record; the transcript (under your harness's projects folder) is the source of truth, regenerable on demand. Focus is capped at ~15 words (the Stop hook enforces). One ledger for all sessions: the Repo column carries `hub` or the satellite repo name.

The live store is `records/sessions.jsonl` (one JSON row per session: `{stamp, session, focus, repo}`, an upsert store refreshed each turn). It is written only through the sanctioned command and the Stop hook, both via `scripts/aios_ledger.py`:

    python3 scripts/aios_ledger.py upsert-session --session <id> --stamp 'YYYY-MM-DD HHMM' --repo <name>

The deny hook (`.claude/hooks/ledger-guard.py`) blocks a raw Edit/Write or shell-redirect of the ledger. The markdown table below is the retired, human-readable mirror kept through the migration bake; do not hand-edit it.

| Date | Session ID | Focus | Repo |
| --- | --- | --- | --- |
