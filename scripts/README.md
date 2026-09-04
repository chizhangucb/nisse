# scripts/

Deterministic mechanics. Skills route judgment; scripts do mechanics. If a step needs no model, it belongs here as plain code.

- Tests live in `scripts/tests/`.
- A script survives only while something calls it. Nothing here runs behind a session.

What ships:

- `setup.py`: first-run personalization and toolchain check.
- `transcript_quality_score.py`: deterministic garble detector for meeting captures (no model, no cost); checks ingest and verifies re-transcriptions.
- `wiki_retranscribe.py`: AssemblyAI re-transcription engine (local audio in, verbatim `_asr.md` mirror out, verify-or-abort, cost cap), driven by `/wiki-retranscribe`. Needs `ASSEMBLYAI_API_KEY`.

Each script states what it reads and writes at the top of the file.
