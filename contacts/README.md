# contacts/

The local contact store: two JSONL files managed by `scripts/contacts.py`, machine-written and never hand-edited. Identity resolution for the wiki's proper-noun pass; wiki entity pages are the curated layer on top.

- `contacts.jsonl`: one contact per line, keyed by slug. Canonical name, status (`confirmed` or `best_read`), affiliation, role, aliases (the ASR variants and misspellings that resolve to this person), channels, links, and the `wiki:` entity page when one exists.
- `not_names.jsonl`: the anti-registry, one verbatim `artifact -> what it really was` line per row. A name listed there never resolves to a person, and the exclusion beats every alias. It fills up fast once real transcripts flow; keep it.

Both files ship with FAKE example rows. Delete them with the rest of the examples.

```
python3 scripts/contacts.py resolve "Sam Reveara"   # who is this?
python3 scripts/contacts.py query riv               # loose search
python3 scripts/contacts.py add --slug ada_lovelace --name "Ada Lovelace"
python3 scripts/contacts.py validate                # exits 1 on violations
```

`validate` also warns about aliases that are risky rather than wrong: a one-word alias that is another contact's real name, or one the anti-registry already excludes. Keep those mappings page-scoped instead of flat aliases.
