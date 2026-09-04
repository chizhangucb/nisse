#!/usr/bin/env python3
"""Local contact store: two JSONL files under `contacts/`.

The store is the single home for who a name refers to: canonical name, ASR
variants and misspellings as `aliases`, `confirmed` vs `best_read` status, and
the exclusion list of ASR artifacts that must never resolve to a person.

Two files, both machine-managed (never hand-edited), one record per line:
    contacts/contacts.jsonl    one contact object per line, keyed by slug
    contacts/not_names.jsonl   one {"line": <verbatim entry>} per artifact

Reads and writes `contacts/` only, plus `wiki/` read-only when validating that
a contact's `wiki:` target exists. Stdlib only. A whole-file rewrite
(save_contact / set_channel / set_link) runs under an flock, so a second writer
never clobbers the file.

Subcommands:
    validate            schema, duplicate slugs and aliases, wiki targets exist;
                        exit 1 on violations
    resolve <name>      exact match (case-insensitive) on names and aliases;
                        a not-name is a hard miss; exit 1 on a miss
    query <substring>   loose search over slugs, names and aliases
    list                one line per contact
    add --slug --name [--status] [--affiliation] [--role]
    add-alias --slug --alias        one ASR variant onto an existing contact
    add-not-name --line             one artifact entry, append-only
    set-channel / set-link

Importable by other scripts:
    load_contacts(root) -> {slug: contact dict}
    resolve(name, root) -> {"status": hit | not_name | miss, ...}
"""

import argparse
import fcntl
import json
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DIRNAME = "contacts"
CONTACTS_FILE = "contacts.jsonl"
NOT_NAMES_FILE = "not_names.jsonl"
LOCKFILE = ".contacts.lock"

STATUSES = ("confirmed", "best_read")
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_]*")
HAN_ONLY_RE = re.compile(r"^[㐀-䶿一-鿿]+$")
# Controlled vocabulary for the channels map. Links are freeform artifact
# pointers (a LinkedIn or X profile, a relevant doc), keyed by a label.
CHANNEL_KEYS = ("telegram", "email", "whatsapp", "linkedin", "x")
# order is the on-disk field order; every contact row carries all of them
FIELDS = ("slug", "name", "status", "affiliation", "role", "aliases", "channels",
          "links", "wiki", "source", "notes")
LIST_FIELDS = ("aliases",)
MAP_FIELDS = ("channels", "links")


class ContactError(Exception):
    pass


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #

def contacts_dir(root=None):
    return os.path.join(root or REPO, DIRNAME)


def contacts_file(root=None):
    return os.path.join(contacts_dir(root), CONTACTS_FILE)


def not_names_file(root=None):
    return os.path.join(contacts_dir(root), NOT_NAMES_FILE)


def slugify(name):
    """`Sam Rivera` -> `sam_rivera`. Parentheticals and non-ASCII drop out."""
    base = re.sub(r"\([^)]*\)", " ", name or "")
    base = base.lower().replace("&", " and ")
    base = re.sub(r"[^a-z0-9]+", "_", base)
    return base.strip("_")


def blank_contact(slug, name, status="best_read", affiliation="", role=""):
    return {"slug": slug, "name": name, "status": status,
            "affiliation": affiliation, "role": role, "aliases": [],
            "channels": {}, "links": {}, "wiki": "", "source": "", "notes": ""}


def _scalar(v):
    """JSON scalar -> string. A null is an absent value, never the text "None"."""
    if v is None or isinstance(v, (list, dict)):
        return ""
    return str(v)


def _normalize(data, slug):
    out = blank_contact(slug, _scalar(data.get("name")) or slug)
    for k in FIELDS:
        if k not in data:
            continue
        v = data[k]
        if k in LIST_FIELDS:
            out[k] = list(v) if isinstance(v, list) else ([v] if v else [])
        elif k in MAP_FIELDS:
            out[k] = v if isinstance(v, dict) else {}
        else:
            out[k] = _scalar(v)
    out["_missing"] = [k for k in FIELDS if k not in data]
    return out


def _read_jsonl(path):
    """(rows, damage) for a jsonl file: every JSON-object line in file order,
    plus one `<file>:<lineno>: <why>` string per line that is not one.

    Damage is returned rather than swallowed because every writer here rewrites
    the whole file: a line this reader drops silently would be deleted from disk
    by the next save. `_update` refuses to write while damage exists.
    """
    rows, damage = [], []
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    damage.append(f"{name}:{n}: not valid JSON")
                    continue
                if not isinstance(obj, dict):
                    damage.append(f"{name}:{n}: not a JSON object")
                    continue
                rows.append(obj)
    except OSError:
        return [], []
    return rows, damage


def load_store(root=None):
    """({slug: contact dict}, damage) for `contacts/contacts.jsonl`.

    Damage covers unreadable lines, rows with no slug, and duplicate slugs: the
    three ways a row can exist on disk but not in the returned store.
    """
    rows, damage = _read_jsonl(contacts_file(root))
    out = {}
    for n, data in enumerate(rows, 1):
        slug = _scalar(data.get("slug")).strip()
        if not slug:
            damage.append(f"{CONTACTS_FILE}: row {n} has no slug")
            continue
        if slug in out:
            damage.append(f"{CONTACTS_FILE}: duplicate slug '{slug}', "
                          f"row {n} shadows an earlier row")
            continue
        out[slug] = _normalize(data, slug)
    return out, damage


def load_contacts(root=None):
    """{slug: contact dict} for every row in `contacts/contacts.jsonl`. Rows the
    store cannot hold are reported by `load_store`, and block every write."""
    return load_store(root)[0]


def _dump_store(store, root):
    """Write the whole contacts.jsonl (sorted by slug). The caller MUST hold the
    lock; the write is atomic via a temp file + os.replace."""
    os.makedirs(contacts_dir(root), exist_ok=True)
    tmp = contacts_file(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for slug in sorted(store):
            row = {k: store[slug][k] for k in FIELDS}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, contacts_file(root))


def _update(root, mutate):
    """Read-modify-write the whole store UNDER an flock, so a concurrent writer
    never clobbers the file. `mutate` gets the loaded {slug: contact} store,
    changes it in place, and may return a value passed back to the caller.

    Refuses to write a store with damaged rows: the rewrite would delete them.
    Fix them by hand (`contacts.py validate` names each one), then retry.
    """
    d = contacts_dir(root)
    os.makedirs(d, exist_ok=True)
    lock = os.open(os.path.join(d, LOCKFILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store, damage = load_store(root)
        if damage:
            raise ContactError(
                "refusing to write: the store has row(s) a rewrite would drop; "
                "run `contacts.py validate` and fix them first: "
                + "; ".join(damage))
        result = mutate(store)
        _dump_store(store, root)
        return result
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        os.close(lock)


def save_contact(contact, root=None):
    """Upsert one contact into the JSONL store (whole-file rewrite, flocked)."""
    row = {k: contact[k] for k in FIELDS}
    _update(root, lambda store: store.__setitem__(row["slug"], row))


def add_contact(contact, root=None):
    """Insert one contact, refusing a slug the store already carries. The check
    runs inside the lock, so two concurrent adds cannot both win."""
    row = {k: contact[k] for k in FIELDS}
    slug = row["slug"]
    if not SLUG_RE.fullmatch(slug or ""):
        raise ContactError(f"'{slug}' is not a usable slug (lowercase letters, "
                           f"digits and underscores); a row with no slug is "
                           f"invisible to resolve and list")

    def mut(store):
        if slug in store:
            raise ContactError(f"contact '{slug}' already exists")
        store[slug] = row
        return row
    return _update(root, mut)


def add_alias(slug, alias, root=None):
    """Add one ASR variant or misspelling to an existing contact."""
    alias = (alias or "").strip()
    if not alias:
        raise ContactError("empty alias")

    def mut(store):
        if slug not in store:
            raise ContactError(f"no contact '{slug}'")
        aliases = store[slug]["aliases"]
        if any(a.strip().lower() == alias.lower() for a in aliases):
            raise ContactError(f"'{alias}' is already an alias of {slug}")
        aliases.append(alias)
        return store[slug]
    return _update(root, mut)


ARROW_RE = re.compile(r"\s*(?:->|→)\s*")


def _split_arrow(line):
    parts = ARROW_RE.split(line, 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def add_not_name(line, root=None):
    """Append one `artifact -> what it really was` entry to not_names.jsonl.

    Append-only and unlocked-safe: unlike the contact store this file is never
    rewritten, so a single O_APPEND write cannot lose an existing row.
    """
    line = (line or "").strip()
    if not line:
        raise ContactError("empty not-name entry")
    if not ARROW_RE.search(line):
        raise ContactError("a not-name entry names what was really said: "
                           "'<as heard>' -> <what it was>")
    if any(line == e["line"] for e in load_not_names(root)):
        raise ContactError(f"{NOT_NAMES_FILE} already carries that entry")
    os.makedirs(contacts_dir(root), exist_ok=True)
    with open(not_names_file(root), "a", encoding="utf-8") as f:
        f.write(json.dumps({"line": line}, ensure_ascii=False) + "\n")
    return line


def load_not_names(root=None):
    """[{line, artifacts, meaning}] from `contacts/not_names.jsonl`.

    Each row stores its verbatim text as `{"line": ...}`; `artifacts` (the
    renderings that must never resolve to a person) and `meaning` (what was
    really said) are parsed from it here, so the parsing lives in one place.
    """
    out = []
    for row in _read_jsonl(not_names_file(root))[0]:
        line = str(row.get("line", ""))
        if not line:
            continue
        left, meaning = _split_arrow(line)
        quoted = re.findall(r'"([^"]+)"', left)
        artifacts = quoted or ([left.strip()] if left.strip() else [])
        out.append({"line": line,
                    "artifacts": [a.strip() for a in artifacts if a.strip()],
                    "meaning": meaning.strip()})
    return out


def not_name_index(root=None):
    """lowercased artifact -> its entry."""
    idx = {}
    for entry in load_not_names(root):
        for a in entry["artifacts"]:
            idx.setdefault(a.lower(), entry)
    return idx


# --------------------------------------------------------------------------- #
# resolve / query
# --------------------------------------------------------------------------- #

def resolve(name, root=None, contacts=None, not_names=None):
    """Case-insensitive exact match on canonical names and aliases.

    Returns {"status": "hit"|"not_name"|"miss", "contact":..., "reason":...}.
    The not-names list wins over everything: an ASR artifact never becomes a
    person.
    """
    key = (name or "").strip().lower()
    if not key:
        return {"status": "miss", "contact": None, "reason": "empty name"}
    idx = not_name_index(root) if not_names is None else not_names
    if key in idx:
        entry = idx[key]
        return {"status": "not_name", "contact": None,
                "reason": f"listed in {NOT_NAMES_FILE}: {entry['line']}"}
    store = load_contacts(root) if contacts is None else contacts
    for c in store.values():
        if c["name"].strip().lower() == key:
            return {"status": "hit", "contact": c, "reason": "canonical name"}
    for c in store.values():
        for a in c["aliases"]:
            if a.strip().lower() == key:
                return {"status": "hit", "contact": c, "reason": f"alias '{a}'"}
    return {"status": "miss", "contact": None, "reason": "no contact matches"}


def query(substring, root=None):
    """Loose search: substring of slug, name, or any alias."""
    needle = (substring or "").strip().lower()
    hits = []
    for slug, c in sorted(load_contacts(root).items()):
        blob = " ".join([slug, c["name"], *c["aliases"]]).lower()
        if needle and needle in blob:
            hits.append(c)
    return hits


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #

def validate(root=None):
    """Returns (violations, warnings), both lists of strings."""
    violations, warnings = [], []
    d = contacts_dir(root)
    if not os.path.isdir(d):
        return ["contacts/ does not exist"], []
    store, damage = load_store(root)
    # Rows on disk the store cannot hold: unreadable, slugless, or a duplicate
    # slug shadowing an earlier row. Violations, not warnings, because the next
    # write refuses while any of them stands (see `_update`).
    violations.extend(f"{DIRNAME}/{d}" for d in damage)
    _, nn_damage = _read_jsonl(not_names_file(root))
    violations.extend(f"{DIRNAME}/{d}" for d in nn_damage)
    alias_owner = {}
    for slug, c in sorted(store.items()):
        f = f"{DIRNAME}/{CONTACTS_FILE}:{slug}"
        if c["_missing"]:
            violations.append(f"{f}: missing key(s) {', '.join(c['_missing'])}")
        if not SLUG_RE.fullmatch(slug):
            violations.append(f"{f}: slug is not lowercase letters, digits and "
                              f"underscores")
        if c["status"] not in STATUSES:
            violations.append(f"{f}: status '{c['status']}' is not one of "
                              f"{'/'.join(STATUSES)}")
        if not c["name"]:
            violations.append(f"{f}: empty name")
        if "internal" in c["affiliation"].lower() and not c["role"].strip():
            warnings.append(f"{f}: internal contact has no role; a row with no "
                            f"role says nothing about who they are")
        if c["wiki"]:
            target = os.path.join(root or REPO, "wiki", c["wiki"])
            if not os.path.exists(target):
                violations.append(f"{f}: wiki target wiki/{c['wiki']} does not exist")
        for ch, val in (c["channels"] or {}).items():
            if ch not in CHANNEL_KEYS:
                violations.append(f"{f}: unknown channel '{ch}', not one of "
                                  f"{'/'.join(CHANNEL_KEYS)}")
            if not str(val).strip():
                warnings.append(f"{f}: channel '{ch}' has an empty value")
        for label, url in (c["links"] or {}).items():
            if not str(url).strip():
                warnings.append(f"{f}: link '{label}' has an empty value")
        for a in c["aliases"]:
            k = a.strip().lower()
            if not k:
                continue
            if k == c["name"].strip().lower():
                warnings.append(f"{f}: alias '{a}' repeats the canonical name")
            if k in alias_owner and alias_owner[k] != c["slug"]:
                violations.append(f"alias '{a}' claimed by both "
                                  f"{alias_owner[k]} and {c['slug']}")
            alias_owner[k] = c["slug"]
    # Two rows with the same canonical name: `resolve` returns whichever it
    # reaches first, with no sign the answer was a coin flip. Real namesakes
    # happen, so this is a warning; disambiguate one of them (a middle name, an
    # affiliation) rather than leaving the toss to dict order.
    by_name = {}
    for slug, c in sorted(store.items()):
        by_name.setdefault(c["name"].strip().lower(), []).append(slug)
    for k, owners in sorted(by_name.items()):
        if k and len(owners) > 1:
            warnings.append(f"canonical name '{k}' is claimed by "
                            f"{', '.join(owners)}; resolve returns whichever it "
                            f"reaches first, so disambiguate one of them")
    names = {k: owners[0] for k, owners in by_name.items()}
    for k, owner in sorted(alias_owner.items()):
        if k in names and names[k] != owner:
            violations.append(f"alias '{k}' of {owner} is the canonical name "
                              f"of {names[k]}")
    # Alias inflation guard: a one-word alias that is also somebody else's real
    # given or family name resolves plainly to the wrong person, and `resolve`
    # carries no per-alias confidence. Exact alias-to-alias collisions are
    # already violations above. The extra Han suffix index covers unspaced
    # Chinese full-name forms, where whitespace tokenization has no given-name
    # boundary. Keep risky mappings page-scoped (in the contact's source field
    # or the source page's callout), not flat aliases.
    name_tokens = {}
    for slug, c in store.items():
        for tok in c["name"].strip().lower().split():
            name_tokens.setdefault(tok, set()).add(slug)
        for form in (c["name"], *c["aliases"]):
            text = form.strip().lower()
            if HAN_ONLY_RE.fullmatch(text) and len(text) >= 3:
                # Chinese family names are usually one character; the final
                # two characters are the useful conservative given-name atom.
                name_tokens.setdefault(text[-2:], set()).add(slug)
    for k, owner in sorted(alias_owner.items()):
        if len(k.split()) != 1:
            continue
        if HAN_ONLY_RE.fullmatch(k) and len(k) == 1:
            warnings.append(f"alias '{k}' of {owner} is a single-character Han "
                            f"name fragment; keep it page-scoped instead")
            continue
        others = sorted(name_tokens.get(k, set()) - {owner})
        if others:
            warnings.append(f"alias '{k}' of {owner} is also a name word of "
                            f"{', '.join(others)}; single-token aliases that are "
                            f"another person's real name resolve to the wrong "
                            f"person, keep it page-scoped instead")
    nn = not_name_index(root)
    for k, owner in sorted(alias_owner.items()):
        if k in nn:
            warnings.append(f"alias '{k}' of {owner} is also a {NOT_NAMES_FILE} "
                            f"entry; the exclusion wins, so it will never resolve")
    for k, slug in sorted(names.items()):
        if k in nn:
            warnings.append(f"canonical name of {slug} is also a "
                            f"{NOT_NAMES_FILE} entry; it will never resolve")
    return violations, warnings


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_validate(args):
    violations, warnings = validate(args.root)
    for w in warnings:
        print(f"warn: {w}")
    for v in violations:
        print(f"VIOLATION: {v}")
    n = len(load_contacts(args.root))
    print(f"{n} contact(s), {len(violations)} violation(s), "
          f"{len(warnings)} warning(s)")
    return 1 if violations else 0


def cmd_resolve(args):
    res = resolve(args.name, args.root)
    if res["status"] == "hit":
        c = res["contact"]
        print(f"{c['name']} | {c['slug']} | {c['status']} | matched on "
              f"{res['reason']}")
        return 0
    if res["status"] == "not_name":
        print(f"MISS (not a name): {args.name} | {res['reason']}")
        return 1
    print(f"MISS: {args.name} | {res['reason']}")
    return 1


def cmd_query(args):
    hits = query(args.substring, args.root)
    for c in hits:
        aliases = ", ".join(c["aliases"])
        print(f"{c['slug']:<28} {c['name']:<32} {c['status']:<10} {aliases}")
    print(f"{len(hits)} match(es)")
    return 0 if hits else 1


def cmd_list(args):
    store = load_contacts(args.root)
    print(f"{'SLUG':<28} {'NAME':<32} {'STATUS':<10} {'AFFILIATION':<20} "
          f"{'ROLE':<28} ALIASES")
    for slug, c in sorted(store.items()):
        print(f"{slug:<28} {c['name']:<32} {c['status']:<10} "
              f"{c['affiliation']:<20} {c['role']:<28} {len(c['aliases'])}")
    print(f"{len(store)} contact(s)")
    return 0


def cmd_add(args):
    c = blank_contact(args.slug, args.name, args.status, args.affiliation or "",
                      args.role or "")
    try:
        add_contact(c, args.root)
    except ContactError as e:
        print(f"refusing: {e}")
        return 1
    print(f"wrote contact '{args.slug}' to contacts/{CONTACTS_FILE}")
    return 0


def cmd_add_alias(args):
    add_alias(args.slug, args.alias, args.root)
    print(f"contacts/{CONTACTS_FILE}: {args.slug} alias + {args.alias}")
    return 0


def cmd_add_not_name(args):
    add_not_name(args.line, args.root)
    print(f"contacts/{NOT_NAMES_FILE} + {args.line}")
    return 0


def set_channel(slug, channel, value, root=None):
    """Set a controlled channel (telegram/email/...) on a contact and save."""
    if channel not in CHANNEL_KEYS:
        raise ContactError(f"unknown channel '{channel}', not one of "
                           f"{'/'.join(CHANNEL_KEYS)}")

    def mut(store):
        if slug not in store:
            raise ContactError(f"no contact '{slug}'")
        store[slug]["channels"][channel] = value
        return store[slug]
    return _update(root, mut)


def set_link(slug, label, url, root=None):
    """Set a freeform artifact link (linkedin, x, a doc) on a contact."""
    if not (label or "").strip():
        raise ContactError("empty link label")

    def mut(store):
        if slug not in store:
            raise ContactError(f"no contact '{slug}'")
        store[slug]["links"][label.strip()] = url
        return store[slug]
    return _update(root, mut)


def cmd_set_channel(args):
    set_channel(args.slug, args.channel, args.value, args.root)
    print(f"contacts/{CONTACTS_FILE}: {args.slug} channel {args.channel} = "
          f"{args.value}")
    return 0


def cmd_set_link(args):
    set_link(args.slug, args.label, args.url, args.root)
    print(f"contacts/{CONTACTS_FILE}: {args.slug} link {args.label} = {args.url}")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="repo root (default: this repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("validate").set_defaults(fn=cmd_validate)

    p = sub.add_parser("resolve")
    p.add_argument("name")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("query")
    p.add_argument("substring")
    p.set_defaults(fn=cmd_query)

    sub.add_parser("list").set_defaults(fn=cmd_list)

    p = sub.add_parser("add")
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--status", default="best_read", choices=list(STATUSES))
    p.add_argument("--affiliation", default="")
    p.add_argument("--role", default="")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("add-alias")
    p.add_argument("--slug", required=True)
    p.add_argument("--alias", required=True,
                   help="an ASR variant or misspelling of this person's name")
    p.set_defaults(fn=cmd_add_alias)

    p = sub.add_parser("add-not-name")
    p.add_argument("--line", required=True,
                   help='verbatim entry, e.g. \'"crawl code" -> Claude Code\'')
    p.set_defaults(fn=cmd_add_not_name)

    p = sub.add_parser("set-channel")
    p.add_argument("--slug", required=True)
    p.add_argument("--channel", required=True, choices=list(CHANNEL_KEYS))
    p.add_argument("--value", required=True)
    p.set_defaults(fn=cmd_set_channel)

    p = sub.add_parser("set-link")
    p.add_argument("--slug", required=True)
    p.add_argument("--label", required=True)
    p.add_argument("--url", required=True)
    p.set_defaults(fn=cmd_set_link)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ContactError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
