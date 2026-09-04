# Ingest rules

Process rules specific to wiki-ingest. Invariants, shared boilerplate, and precedence live in `wiki/AGENTS.md`.

## Raw files and source pages

- **Naming.** Meetings `YYYY-MM-DD_<series_slug>.md`, series not session topic, source-page slug identical to the raw file. Brainstorms `YYYY-MM-DD_<slug>.md`. Clippings and documents keep their original names.
- **Never invent an invitee list.** Leave attendance as captured; `participants:` comes from the transcript or the owner, never a guess.
- **Speaker labels are claims.** Mirror `Speaker 1/2`-style labels exactly in the raw file; a guessed name in a verbatim mirror is unrecoverable. Speaker identity goes on the source page via a `**Name gaps:**` line, tagged best-guess when it is one.
- **Name-gap test: would a wrong read put a false fact in the wiki?** Run `python3 scripts/contacts.py resolve <name>` first. Flag genuine identity questions (a miss against the contact store and `context/about-team.md`, an unconfirmable spelling); a `not_name` result is an ASR artifact, never a person. Do not flag obvious-referent manglings: write the canonical name inline, and carry recurring variants to the checkpoint. Once approved: `contacts.py add-alias` for a person, `contacts.py add-not-name` for an artifact that is nobody, a `wiki/metadata/name_registry.md` row for any other proper noun.

## Meeting tiers

- **Full source page if any of:** an external counterparty present; a decision made; anything matching a `confidential:` lens; 3+ expected signals at first read. *Decision test:* a resolved commitment someone would cite later (an owner accepted a named action, a choice closed, a number/date/policy set). Status updates do not count; ambiguous → err toward the page.
- **Otherwise ledger tier:** one annotated row in `wiki/metadata/sources.jsonl`, no source page, no distill entry. Rule 7 still applies: a sensitive capture's line stays vague.
- **Escape hatches:** the owner's "full page" overrides; triage can promote a ledger line to a page later.

## Retrieval

- **Declare before writing:** full / partial / excerpts. Try the full-content path first; note the gap in the page's `> [!warning] Capture caveats` callout when partial.
- **Garbled capture:** check with `python3 scripts/transcript_quality_score.py <mirror>`; land it anyway, flag the garble prominently on the source page, and hand recovery to `/wiki-retranscribe` (tier 2, needs `ASSEMBLYAI_API_KEY`). Never mine garbled fragments as facts.

## Provider traps

Observations, not invariants; each carries an observed date. When a run contradicts one, fix or delete the line in the same session; hygiene flags lines older than ~1 month.

- (add your own as you hit them, e.g. "site X blocks the default fetcher: use Y (observed YYYY-MM)")
