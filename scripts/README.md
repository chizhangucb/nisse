# scripts/

Deterministic mechanics. Skills route judgment; scripts do mechanics. If a step needs no model, it belongs here as plain code.

- Tests live in `scripts/tests/`.
- A script survives only while something calls it. Nothing here runs behind a session.

What ships:

- `wiki_check.py`: the one mechanical enforcement point for `wiki/AGENTS.md`. Prints `<page> | <rule> | <fix>` per violation, exits non-zero when the wiki is dirty. Run it on any wiki root: `python3 scripts/wiki_check.py wiki`.
- `wiki_ledger.py`: the only sanctioned writer for `wiki/metadata/*.jsonl`. Append-only, one whole line under an flock. Hand-editing those files breaks the append contract.
- `wiki_ingest.py`: mechanical half of ingest. Acquires meetings, mirrors them to `raw/`, scaffolds the source page, writes the index and log lines. Judgment calls come back as NEEDS-JUDGMENT lines for the skill.
- `wiki_distill_apply.py`: applies a distill plan's evidence bullets to their pages and stamps `distilled:`.
- `evidence_archive.py`: rotates folded evidence off a living page into `wiki/archive/<same-subpath>.md`, leaving a dated pointer. Triage calls it; distill never does.
- `transcript_quality_score.py`: deterministic garble detector for meeting captures (no model, no cost); checks ingest and verifies re-transcriptions.
- `wiki_retranscribe.py`: AssemblyAI re-transcription engine (local audio in, verbatim `_asr.md` mirror out, verify-or-abort, cost cap), driven by `/wiki-retranscribe`. Needs `ASSEMBLYAI_API_KEY`.

Each script states what it reads and writes at the top of the file.
