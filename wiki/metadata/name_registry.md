# Name Registry

Canonical spellings for proper nouns that transcription mangles: companies, products, places. One row per resolved name: how it was misheard, what it actually is, and the source that settled it.

People are not here. A person's mishearings live as `aliases` on their row in `contacts/contacts.jsonl`, and the anti-registry (things that look like names and are not) is `contacts/not_names.jsonl`; both are read with `python3 scripts/contacts.py resolve <name>`. Proper-noun resolution order is in `wiki/AGENTS.md`.

| As heard | Canonical | Settled by |
|---|---|---|
| (example) "Acne Dev Tools" | Acme DevTools | 2026-01-05 weekly sync, slide title |
