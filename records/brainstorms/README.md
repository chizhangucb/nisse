# brainstorms/

Discovery and grilling sessions, one dated file each: `YYYY-MM-DD-<slug>.md`. The assistant checkpoints every question and answer to the file as the conversation runs, so nothing is lost if the session dies. Decisions extracted from a brainstorm still get their own block in `../decisions.jsonl` (via `scripts/aios_ledger.py append-decision`); the brainstorm holds the full Q&A story the decision points back to.
