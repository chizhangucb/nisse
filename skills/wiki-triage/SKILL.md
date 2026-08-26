---
name: wiki-triage
description: Promote wiki evidence into current truth and keep the wiki semantically healthy - the weekly-ish interactive pass that recaps fresh evidence per page, proposes Current truth and Open decisions updates for the owner's approval, runs the capture queue with one disposition per item (Promote / Keep / Skip / Retire), and judges the semantic health checks (contradictions, superseded claims, confidential leakage) over the mechanical findings from scripts/hygiene_check.py. Use whenever the owner says triage, lint the wiki, promote the evidence, update current truth, resolve the open blocks, run the weekly wiki review, or asks whether confidential material has leaked. Also the natural follow-up once wiki-distill has landed evidence. Not for landing sources (wiki-ingest), not for extracting evidence to pages (wiki-distill), not for answering questions from the wiki.
---

Interactive session: **scope → sweep → recap → queue → lint → write → report**. Weekly-ish; the one wiki operation that is a conversation, not a batch.

Read `wiki/CLAUDE.md`, `wiki/rules.md`, and `references/triage-rules.md` first, in full. Precedence: schema > shared rules > skill rules > this file.

## Is / is not

| Yes | No |
|-----|-----|
| Rewrite `# Current truth`, `## Open decisions`, `synthesis/` (Rule 6: triage only, the owner's yes per page) | Appending `# Evidence` (wiki-distill) |
| Capture-queue dispositions on empty-`triaged:` brainstorms and clippings | Landing sources (wiki-ingest); if undistilled sources block the recap, point at wiki-distill first |
| Annotations: Superseded callouts, Open-block resolutions | Editing or deleting evidence bullets, or anything in `raw/` |
| Health checks; tag-merge proposals (only the owner merges) | Answering questions from the wiki |

## The pass

1. **Confirm scope.** Default window: since the last `triage` entry in `wiki/metadata/log.jsonl`; never all-time unasked. The owner can narrow by page or topic; health checks stay wiki-wide unless narrowed too. Get the nod, then run without stops.
2. **Sweep before talking:** pages with fresh in-window `# Evidence` plus pages never promoted; the capture queue; run `python3 scripts/hygiene_check.py` for the mechanical wiki findings.
3. **Recap and propose, page by page:** current truth (or "none yet") → new evidence with trust classes → proposed `# Current truth (last updated: YYYY-MM-DD)` → `## Open decisions` resolve / keep / add. The owner answers promote / edit / skip. **Promotions replace or consolidate: `# Current truth` caps at 7 top-level bullets; growth past it forces a demotion to Evidence.** Semantics: `references/triage-rules.md`.
4. **Queue:** one disposition per item (Promote / Keep / Skip / Retire), one-line reason each; table in `references/triage-rules.md`.
5. **Lint, judgment half only:** judge the semantic checks over the script's findings (contradictions, superseded claims, leakage, gaps); ranked, leakage on top, each with a proposed fix or an honest "no action worth taking". Mechanical checks are the script's job; never re-derive them.
6. **Write only what the owner approved, then report the diff** per the write discipline in `references/triage-rules.md`. Close with the one thing most worth a follow-up ingest.
