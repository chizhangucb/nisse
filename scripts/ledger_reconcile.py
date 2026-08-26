#!/usr/bin/env python3
"""Reconcile the JSONL ledgers with their retiring markdown mirrors (CHI-313).

During the migration bake, a session whose deny hook was not yet active can
write a block/row straight to the old markdown file (decisions.md,
sessions_index.md, log.md, the sources shards) instead of through the append
command. That block is safe in the markdown but is not yet in the JSONL truth.

This closes the gap WITHOUT losing anything: the JSONL is authoritative (it
carries CLI/hook writes the markdown mirror can miss, and sessions.jsonl is the
live store while sessions_index.md is frozen), so we UNION - keep every JSONL
row, and add only the markdown blocks/rows whose key is not already present.
JSONL wins on any key conflict. Every file is rewritten OLDEST-first (newest at
the bottom) so all four share one append-consistent storage order.

Idempotent: a second run adds nothing. Run it whenever you want to be sure the
markdown and JSONL agree, and once more at bake-end right before dropping the
markdown writers.

    python3 scripts/ledger_reconcile.py            # reconcile, report, write
    python3 scripts/ledger_reconcile.py --dry-run  # report only, write nothing
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aios_ledger as L  # noqa: E402  (sibling import needs the path insert above)
import ledger_backfill as B  # noqa: E402


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _union(existing, incoming, key):
    """existing (JSONL truth) wins; append only incoming rows with a new key.
    Returns (merged_rows, added_rows)."""
    seen = {key(r) for r in existing}
    added = [r for r in incoming if key(r) not in seen]
    return existing + added, added


# ---------------------------------------------------------------------------

def _decision_key(r):
    s, st = r.get("session"), r.get("stream")
    return (s, st) if s else ("legacy", r.get("date"), r.get("title"))


def _parse_md_decisions(hub):
    blocks = []
    hist = os.path.join(hub, "records", "decisions_history", "*.md")
    for shard in sorted(glob.glob(hist)):
        blocks += B._parse_decision_blocks(open(shard, encoding="utf-8").read(),
                                           anchor_marker=False)
    dm = os.path.join(hub, "records", "decisions.md")
    if os.path.exists(dm):
        blocks += B._parse_decision_blocks(open(dm, encoding="utf-8").read(),
                                           anchor_marker=True)
    return [B._block_to_row(h, b) for h, b in blocks]


def reconcile_decisions(hub, dry_run):
    # Append-log: add any markdown-only block via the atomic append (lock-safe on
    # a live tree); never full-rewrite, so a concurrent append is never clobbered.
    existing = L.read_decisions(hub)
    md = _parse_md_decisions(hub)
    _, added = _union(existing, md, _decision_key)
    if not dry_run:
        for r in added:
            L.append_decision(hub, date=r["date"], title=r["title"],
                              session=r.get("session") or "legacy",
                              stream=r.get("stream") or "legacy",
                              body=r["body"])
    return added, len(existing) + (0 if dry_run else len(added))


def reconcile_sessions(hub, dry_run):
    # Upsert store: read-modify-write under the sessions flock, so this both
    # closes any gap AND re-sorts the file oldest-first without racing a Stop hook.
    if dry_run:
        existing = L.read_rows(os.path.join(hub, *L.SESSIONS_JSONL))
        md = B_import_session_rows(hub)
        _, added = _union(existing, md, lambda r: L._strip_id(r.get("session")))
        return added, len(existing) + len(added)
    with L._SessionsLock(hub):
        existing = L.read_rows(os.path.join(hub, *L.SESSIONS_JSONL))
        md = B_import_session_rows(hub)
        merged, added = _union(existing, md, lambda r: L._strip_id(r.get("session")))
        L._write_sessions(hub, merged)  # writes oldest-first
    return added, len(merged)


def B_import_session_rows(hub):
    """Parse sessions_index.md rows the way the backfill does, without writing."""
    path = os.path.join(hub, "records", "sessions_index.md")
    if not os.path.exists(path):
        return []
    lines = open(path, encoding="utf-8").read().splitlines()
    sep = next((i for i, ln in enumerate(lines)
                if ln.lstrip().startswith("|")
                and set(ln.replace("|", "").strip()) <= {"-", " "} and "-" in ln), None)
    if sep is None:
        return []
    out = []
    for ln in lines[sep + 1:]:
        if not ln.lstrip().startswith("|"):
            break
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 4:
            out.append({"stamp": cells[0], "session": cells[1].rstrip("…"),
                        "focus": cells[2], "repo": cells[3]})
    return out


def reconcile_wiki_log(hub, dry_run):
    existing = L.read_wiki_log(hub)
    md = []
    meta = os.path.join(hub, "wiki", "metadata")
    for shard in sorted(glob.glob(os.path.join(meta, "log_history", "*.md"))):
        md += B._parse_log_lines(open(shard, encoding="utf-8").read(),
                                 anchor_marker=False)
    live = os.path.join(meta, "log.md")
    if os.path.exists(live):
        md += B._parse_log_lines(open(live, encoding="utf-8").read(),
                                 anchor_marker=True)
    _, added = _union(existing, md,
                      lambda r: (r.get("date"), r.get("op"), r.get("detail")))
    if not dry_run:  # append-log: atomic append of stragglers only
        for r in added:
            L.append_wiki_log(hub, date=r["date"], op=r["op"], detail=r["detail"])
    return added, len(existing) + (0 if dry_run else len(added))


def reconcile_wiki_sources(hub, dry_run):
    existing = L.read_wiki_sources(hub)
    md = []
    shard_dir = os.path.join(hub, "wiki", "metadata", "index")
    for shard in sorted(glob.glob(os.path.join(shard_dir, "sources-*.md"))):
        import re
        m = re.search(r"sources-(\d{4}-\d{2})\.md$", shard)
        month = m.group(1) if m else ""
        for ln in open(shard, encoding="utf-8"):
            if not ln.startswith("- "):
                continue
            raw = ln[2:].rstrip("\n")
            sm = B.SLUG_RE.match(ln)
            md.append({"month": month, "slug": sm.group(1) if sm else "", "raw": raw})
    _, added = _union(existing, md, lambda r: r.get("slug") or r.get("raw"))
    if not dry_run:  # append-log: atomic append of stragglers only
        for r in added:
            L.append_wiki_source(hub, month=r["month"], slug=r.get("slug", ""),
                                 raw=r["raw"])
    return added, len(existing) + (0 if dry_run else len(added))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=os.path.dirname(HERE))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    hub = os.path.abspath(os.path.expanduser(args.hub))

    for name, fn in [("decisions", reconcile_decisions),
                     ("sessions", reconcile_sessions),
                     ("wiki log", reconcile_wiki_log),
                     ("wiki sources", reconcile_wiki_sources)]:
        added, total = fn(hub, args.dry_run)
        tag = "WOULD add" if args.dry_run else "added"
        print(f"{name}: {tag} {len(added)} markdown-only row(s); {total} total")
        for r in added:
            label = (r.get("title") or r.get("detail") or r.get("slug")
                     or r.get("session"))
            when = r.get("date") or r.get("stamp") or r.get("month")
            print(f"    + {when} | {str(label)[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
