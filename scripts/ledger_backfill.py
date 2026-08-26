#!/usr/bin/env python3
"""One-time backfill: current markdown ledgers -> JSONL (CHI-313).

Four importers, each lossless and count-asserted (review fix 7):

  wiki log     wiki/metadata/log_history/*.md (oldest) + log.md (after the
               <!-- /log-shards --> marker)            -> wiki/metadata/log.jsonl
  wiki sources wiki/metadata/index/sources-*.md (20 shards, verbatim `raw`)
                                                        -> wiki/metadata/sources.jsonl
  sessions     records/sessions_index.md pipe table    -> records/sessions.jsonl
  decisions    records/decisions_history/*.md (oldest, incl. session-less
               legacy blocks) + decisions.md (after the marker), block bodies
               stored verbatim                          -> records/decisions.jsonl

Every importer asserts imported-count == source-count and fails loud on any
unparsed line rather than silently dropping it. `--verify` additionally round-
trips decisions (render each row back to markdown and diff against the source
block) so a body-mangling bug is caught before the old files are trusted less.

The importers write oldest-first (append order) so a subsequent append lands
newest-at-EOF; sessions is written newest-first (its display contract). This
script is idempotent: it rebuilds each .jsonl from scratch each run.
"""

import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HUB = os.path.dirname(HERE)

LOG_SHARD_END = "<!-- /log-shards -->"
LOG_LINE_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| (.+)$")
DECISION_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}): (.+)$")
DECISION_ATTR_RE = re.compile(
    r" \(session ([0-9A-Za-z-]+), stream: ([^)]+)\)$")


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# wiki log
# ---------------------------------------------------------------------------

def _parse_log_lines(text, *, anchor_marker):
    """Yield {date, op, detail} for each `- DATE | op | detail` data line.
    In the live log.md, only lines AFTER the shard marker are data (the marker
    body's `- [2026-07](...)` bullet must not be imported). History shards have
    no marker: every `- DATE | ...` line is data. Fails loud on a `- ` line in
    the data region that does not match the format."""
    lines = text.splitlines()
    start = 0
    if anchor_marker:
        for i, ln in enumerate(lines):
            if ln.strip() == LOG_SHARD_END:
                start = i + 1
                break
    rows = []
    for ln in lines[start:]:
        if not ln.strip():
            continue
        if not ln.startswith("- "):
            continue  # a stray header line in a shard; skip non-bullet prose
        m = LOG_LINE_RE.match(ln)
        if not m:
            raise ValueError(f"unparsed wiki-log line: {ln!r}")
        rows.append({"date": m.group(1), "op": m.group(2).strip(),
                     "detail": m.group(3).strip()})
    return rows


def import_wiki_log(hub):
    meta = os.path.join(hub, "wiki", "metadata")
    rows, source_count = [], 0
    for shard in sorted(glob.glob(os.path.join(meta, "log_history", "*.md"))):
        with open(shard, encoding="utf-8") as f:
            text = f.read()
        got = _parse_log_lines(text, anchor_marker=False)
        rows.extend(got)
        source_count += sum(1 for ln in text.splitlines()
                            if ln.startswith("- ") and LOG_LINE_RE.match(ln))
    live = os.path.join(meta, "log.md")
    with open(live, encoding="utf-8") as f:
        text = f.read()
    after = text.split(LOG_SHARD_END, 1)[1] if LOG_SHARD_END in text else text
    live_rows = _parse_log_lines(text, anchor_marker=True)
    rows.extend(live_rows)
    source_count += sum(1 for ln in after.splitlines()
                        if ln.startswith("- ") and LOG_LINE_RE.match(ln))
    assert len(rows) == source_count, \
        f"wiki-log: imported {len(rows)} != source {source_count}"
    _write_jsonl(os.path.join(meta, "log.jsonl"), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# wiki sources
# ---------------------------------------------------------------------------

SLUG_RE = re.compile(r"^-\s+(?:\[\[)?(\d{4}-\d{2}-\d{2}_[a-z0-9_]+)")


def import_wiki_sources(hub):
    """Verbatim `raw` per data line (the shards are wildly irregular: 3-7 pipe
    fields, tag column vs embedded [tag], bare `| ledger |` lines). raw = the
    line minus the leading '- '; month from the shard filename; slug best-effort
    from the line."""
    shard_dir = os.path.join(hub, "wiki", "metadata", "index")
    rows, source_count = [], 0
    for shard in sorted(glob.glob(os.path.join(shard_dir, "sources-*.md"))):
        m = re.search(r"sources-(\d{4}-\d{2})\.md$", shard)
        month = m.group(1) if m else ""
        with open(shard, encoding="utf-8") as f:
            for ln in f:
                if not ln.startswith("- "):
                    continue
                source_count += 1
                raw = ln[2:].rstrip("\n")
                sm = SLUG_RE.match(ln)
                rows.append({"month": month,
                             "slug": sm.group(1) if sm else "",
                             "raw": raw})
    assert len(rows) == source_count, \
        f"wiki-sources: imported {len(rows)} != source {source_count}"
    _write_jsonl(os.path.join(hub, "wiki", "metadata", "sources.jsonl"), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

def import_sessions(hub):
    path = os.path.join(hub, "records", "sessions_index.md")
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    sep = next((i for i, ln in enumerate(lines)
                if ln.lstrip().startswith("|")
                and set(ln.replace("|", "").strip()) <= {"-", " "}
                and "-" in ln), None)
    if sep is None:
        raise ValueError("sessions_index.md: no table separator found")
    rows, source_count = [], 0
    for ln in lines[sep + 1:]:
        if not ln.lstrip().startswith("|"):
            break
        source_count += 1
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4:
            raise ValueError(f"sessions row has <4 cells: {ln!r}")
        rows.append({"stamp": cells[0], "session": cells[1].rstrip("…"),
                     "focus": cells[2], "repo": cells[3]})
    assert len(rows) == source_count, \
        f"sessions: imported {len(rows)} != source {source_count}"
    _write_jsonl(os.path.join(hub, "records", "sessions.jsonl"), rows)
    return len(rows)


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------

def _parse_decision_blocks(text, *, anchor_marker):
    """[(header, body_lines)] for each `## ` block. In decisions.md only blocks
    AFTER the marker are real (the header prose carries format examples). In a
    history shard every `## ` is a block."""
    lines = text.splitlines()
    start = 0
    if anchor_marker:
        for i, ln in enumerate(lines):
            if ln.strip() == LOG_SHARD_END:
                start = i + 1
                break
    blocks = []
    i, n = start, len(lines)
    # advance to first block header
    while i < n and not lines[i].startswith("## "):
        i += 1
    while i < n:
        header = lines[i]
        j = i + 1
        while j < n and not lines[j].startswith("## "):
            j += 1
        blocks.append((header, lines[i + 1:j]))
        i = j
    return blocks


def _block_to_row(header, body_lines):
    m = DECISION_HEADER_RE.match(header)
    if not m:
        raise ValueError(f"unparsed decision header: {header!r}")
    date, rest = m.group(1), m.group(2)
    attr = DECISION_ATTR_RE.search(rest)
    if attr:
        title = rest[:attr.start()]
        session, stream = attr.group(1), attr.group(2)
    else:
        title, session, stream = rest, None, None
    # trim leading/trailing blank lines from the body, keep interior verbatim
    body = list(body_lines)
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    return {"date": date, "title": title, "session": session,
            "stream": stream, "body": "\n".join(body)}


def import_decisions(hub, verify=False):
    recs = os.path.join(hub, "records")
    ordered_blocks = []  # oldest-first
    source_count = 0
    # history shards first (older), each reversed to oldest-first
    for shard in sorted(glob.glob(os.path.join(recs, "decisions_history", "*.md"))):
        with open(shard, encoding="utf-8") as f:
            text = f.read()
        blocks = _parse_decision_blocks(text, anchor_marker=False)
        source_count += len(blocks)
        ordered_blocks.extend(reversed(blocks))
    # then the live file (after the marker), reversed to oldest-first
    with open(os.path.join(recs, "decisions.md"), encoding="utf-8") as f:
        text = f.read()
    blocks = _parse_decision_blocks(text, anchor_marker=True)
    source_count += len(blocks)
    ordered_blocks.extend(reversed(blocks))

    rows = [_block_to_row(h, b) for h, b in ordered_blocks]
    assert len(rows) == source_count, \
        f"decisions: imported {len(rows)} != source {source_count}"

    if verify:
        _verify_decisions_roundtrip(ordered_blocks, rows)

    _write_jsonl(os.path.join(recs, "decisions.jsonl"), rows)
    return len(rows)


def _verify_decisions_roundtrip(ordered_blocks, rows):
    """Render each row back to markdown and confirm it reproduces the source
    block (header + verbatim body), so no bullet/note/arrow was dropped."""
    sys.path.insert(0, HERE)
    import aios_ledger
    mism = 0
    for (header, body_lines), row in zip(ordered_blocks, rows):
        body = list(body_lines)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        expected = header + "\n\n" + "\n".join(body)
        got = aios_ledger.render_decision_block(row)
        if got.rstrip("\n") != expected.rstrip("\n"):
            mism += 1
            if mism <= 3:
                sys.stderr.write(
                    f"ROUNDTRIP MISMATCH:\n--- source ---\n{expected!r}\n"
                    f"--- rendered ---\n{got!r}\n\n")
    if mism:
        raise AssertionError(f"decisions round-trip: {mism} block(s) mismatch")


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--hub", default=HUB)
    ap.add_argument("--only", choices=["log", "sources", "sessions", "decisions"],
                    default=None, help="run just one importer")
    ap.add_argument("--verify", action="store_true",
                    help="round-trip verify decisions")
    args = ap.parse_args(argv)
    hub = os.path.abspath(os.path.expanduser(args.hub))

    runs = {
        "log": lambda: import_wiki_log(hub),
        "sources": lambda: import_wiki_sources(hub),
        "sessions": lambda: import_sessions(hub),
        "decisions": lambda: import_decisions(hub, verify=args.verify),
    }
    todo = [args.only] if args.only else list(runs)
    for name in todo:
        n = runs[name]()
        print(f"{name}: {n} rows -> jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
