# wiki/

The knowledge layer: everything the system knows with provenance. `wiki/CLAUDE.md` is the schema and it is binding for any work in here; `wiki/rules.md` is the shared process contract.

The loop: **ingest** lands a source (transcript, article, note) as an immutable raw mirror plus a source page; **distill** extracts evidence from source pages onto entity, concept, and synthesis pages, append-only; **triage** promotes evidence into current truth with the owner's yes, and keeps the wiki semantically healthy.

Structure (details and naming rules in the schema):

- `raw/`: immutable verbatim mirrors, split by provenance (`transcripts/` gitignored local-only, `clippings/`, `documents/`, `brainstorms/`, `assets/`).
- `sources/`: one page per ingested source: digest, takeaways, signals. Ships with one clearly-fake example.
- `entities/`: people, companies, products. `concepts/`: ideas and frameworks. `synthesis/`: cross-source conclusions, only ever written with the owner's yes in triage. One fake entity example ships.
- `confidential/`: fail-closed home for sensitive knowledge pages. Routing here is the default when in doubt; day-one existence of this folder is what makes the fail-closed rule enforceable.
- `annex/`: rotated evidence overflow from living pages.
- `metadata/`: index, chronology log, tag registry, name registry; the ledgers the loop needs.
