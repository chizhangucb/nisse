# scripts/

Deterministic pipeline mechanics. Skills route judgment; scripts do mechanics. If a step needs no model, it belongs here as plain code.

- Tests live in `scripts/tests/`.
- Promotion rule: a helper moves here once it has 2+ consumers or a scheduled-job dependency; before that it can live where it's used.
- Anything that executes a gate (push scanning, approval flows) is enforcement machinery: editing it needs the owner's explicit yes every time (`governance/building.md`).

What ships:

- `setup.py`: first-run personalization + toolchain check.
- `hygiene_check.py`: the deterministic workspace health scan (`/hygiene` drives confirm-to-fix). Config seam at the top of the file; tracker checks off by default.
- `session_close.py` + `ledger_lock.py`: the detached sweeper that fills `(pending)` session-ledger rows and appends clearly-decided decision blocks; spawned by the SessionStart hook (`.claude/hooks/`).
- `transcript_quality_score.py`: deterministic garble detector for meeting captures (no model, no cost); gates ingest and verifies re-transcriptions.
- `wiki_retranscribe.py`: tier-2 AssemblyAI re-transcription engine (local audio in, verbatim `_asr.md` mirror out, verify-or-abort, cost cap); driven by `/wiki-retranscribe`.
- `ticket_tracker.py`: tier-2 Linear tracker-drift connector (`governance/ticket-tracker.md`), off by default. `--check` for read-only findings (feeds `hygiene_check.py` group 7 when `NISSE_TRACKER_DRIFT=1`), `--sweep` to apply the evidence-provable auto-fixes and emit a ping. Config-driven: `TICKET_TRACKER_PROJECTS`/`TICKET_TRACKER_KEY_PREFIX`/`TICKET_TRACKER_OWNER_EMAIL` in `.env`; ships wired to Linear as the example provider but the check/sweep logic is tracker-agnostic.
- `daily_maintenance.py`: a DORMANT worked example, not installed anywhere. Shows the pattern for merging several morning checks (hygiene, tracker drift) into one digest sent through one gated notification path. Template to actually schedule it: `scripts/templates/com.example.daily-maintenance.plist.template`.
- `egress_gate/`, `litellm/`, `graphify/`: tier-3 dormant components, each with its own wiring-guide README.

Each script states what it reads and writes at the top of the file.
