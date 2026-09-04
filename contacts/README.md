# contacts/

The local contact store: two JSONL files managed by `scripts/contacts.py`, machine-written and never hand-edited. Identity resolution for the wiki's proper-noun pass; wiki entity pages are the curated layer on top.

- `contacts.jsonl`: one contact per line, keyed by slug. Canonical name, status (`confirmed` or `best_read`), affiliation, role, aliases (the ASR variants and misspellings that resolve to this person), channels, links, and the `wiki:` entity page when one exists.
- `not_names.jsonl`: the anti-registry, one verbatim `artifact -> what it really was` line per row. A name listed there never resolves to a person, and the exclusion beats every alias. It fills up fast once real transcripts flow; keep it.

Both files ship with FAKE example rows. Delete them with the rest of the examples.

```
python3 scripts/contacts.py resolve "Sam Reveara"   # who is this?
python3 scripts/contacts.py query riv               # loose search
python3 scripts/contacts.py add --slug ada_lovelace --name "Ada Lovelace"
python3 scripts/contacts.py add-alias --slug ada_lovelace --alias "Ada Loveless"
python3 scripts/contacts.py add-not-name --line '"term share" -> term sheet'
python3 scripts/contacts.py validate                # exits 1 on violations
```

`validate` names every row the store cannot hold: an unreadable line, a row with no slug, a duplicate slug. Those are violations rather than warnings because every write rewrites `contacts.jsonl` whole, so the script refuses to write at all until they are fixed by hand. It also warns about aliases that are risky rather than wrong: a one-word alias that is another contact's real name, one the anti-registry already excludes, or two people sharing a canonical name. Keep risky mappings page-scoped instead of flat aliases.
