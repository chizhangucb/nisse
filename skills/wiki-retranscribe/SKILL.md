---
name: wiki-retranscribe
description: Re-transcribe a garbled meeting capture through the AssemblyAI engine in scripts/wiki_retranscribe.py (tier-2 connector, needs ASSEMBLYAI_API_KEY). Use whenever a capture comes back garbled, wiki-ingest flags a garble, or the owner says retranscribe, re-transcribe this meeting, or fix the garbled transcript. Not for landing clean captures (wiki-ingest), not for extracting evidence (wiki-distill).
---

# Wiki Retranscribe

Routing stub; the mechanics live in the script. Needs the audio file locally (export it from your capture tool) and `ASSEMBLYAI_API_KEY` (`.env.example`).

1. Run `python3 scripts/wiki_retranscribe.py --audio <file> --slug <slug> --dry-run` to see the plan (cost estimate against the cap, target paths), then rerun without `--dry-run`.
2. The script uploads the audio to AssemblyAI, transcribes with speaker labels, writes the mirror to `wiki/raw/transcripts/<slug>_asr.md` beside the untouched original, and prints both garble scores (`scripts/transcript_quality_score.py`). It aborts without writing when the re-transcription scores no better than the original ("retranscription failed", visible), and refuses meetings estimated over the cost cap.
3. Speaker attribution is a claim, not ground truth: labels stay `Speaker N`; map them to people on the SOURCE PAGE via `**Name gaps:**` with `speaker best-guess (low confidence)` where it is one (per `skills/wiki-ingest/references/ingest-rules.md`). Never edit names into the raw mirror.
4. If the meeting has no source page yet, hand it to wiki-ingest after the mirror lands; if it has one, add `recovered:` frontmatter (engine, date, verdict) to the source page.
