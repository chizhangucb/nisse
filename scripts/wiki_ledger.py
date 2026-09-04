#!/usr/bin/env python3
"""Append-only JSONL stores the wiki flows own.

The two append-only logs that live under the wiki, written one whole line at a
time under an flock and read with a tolerant reader that skips a partial
trailing line:

  wiki/metadata/log.jsonl        one row per wiki operation   {"date","op","detail"}
  wiki/metadata/sources.jsonl    one row per meeting source   {"month","slug","raw"}

The schema requires these files be written ONLY through this module, by hand
via the CLI or in-process by ingest and distill. Hand-editing a JSONL breaks
the append contract below.

Self-contained (stdlib only). The `root` argument is the repo root that holds
`wiki/`.

Append contract: one writer at a time appends one whole encoded line via a
single os.write under an flock (O_APPEND | O_CREAT), ensure_ascii=False. On a
local single-writer-per-file filesystem this removes the read-modify-write
reorder race; the flock + whole-line os.write + a reader that SKIPS any
unparseable or partial trailing line are all load-bearing. Void on NFS / iCloud
/ Dropbox-synced paths. Appends are not fsync'd by default; pass fsync=True.
"""

import fcntl
import json
import os
import re

WIKI_LOG_JSONL = ("wiki", "metadata", "log.jsonl")
WIKI_SOURCES_JSONL = ("wiki", "metadata", "sources.jsonl")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def root_path(root, parts):
    return os.path.join(root, *parts)


# ---------------------------------------------------------------------------
# Low-level append + read primitives (see the module docstring's contract)
# ---------------------------------------------------------------------------

def _append_line(path, line, *, fsync=False):
    """Append one whole line via a single os.write under an flock.

    line must already end in "\n". Creates the file (and its parent dir) if
    absent. The flock serializes concurrent writers on a local FS; the single
    os.write of the whole encoded line keeps a normal append indivisible."""
    if not line.endswith("\n"):
        line += "\n"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = line.encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            os.write(fd, data)
            if fsync:
                os.fsync(fd)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _dumps(row):
    """One JSONL line. ensure_ascii=False keeps CJK names/content readable in
    the diff; field order is the dict's insertion order for a legible git diff."""
    return json.dumps(row, ensure_ascii=False) + "\n"


def read_rows(path):
    """Every well-formed row in a JSONL log, in file (append) order.

    Skips blank lines and any line that does not parse as a JSON object,
    including a truncated trailing line from a crash mid-append. Missing
    file -> []."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except FileNotFoundError:
        return []
    return rows


# ===========================================================================
# Wiki log (append-only)  row: {"date","op","detail"}
# ===========================================================================

def read_wiki_log(root):
    return read_rows(root_path(root, WIKI_LOG_JSONL))


def append_wiki_log(root, *, date, op, detail, fsync=False):
    """Append one wiki-log row. Returns (True, None) or (False, reason)."""
    if not DATE_RE.match(date or ""):
        return False, f"bad date {date!r}"
    op = (op or "").strip()
    if not op or "|" in op:
        return False, f"bad op {op!r}"
    detail = (detail or "").strip()
    if not detail:
        return False, "empty detail"
    row = {"date": date, "op": op, "detail": detail}
    _append_line(root_path(root, WIKI_LOG_JSONL), _dumps(row), fsync=fsync)
    return True, None


# ===========================================================================
# Wiki sources (append-only)  row: {"month","slug","raw", ...structured}
# ===========================================================================
#
# The legacy monthly shards were wildly irregular, so the row always carries
# `raw` = the original line content after the leading "- ". New appends supply
# the same formatted line plus month + slug; readers can re-parse `raw` if they
# need fields.

def read_wiki_sources(root):
    return read_rows(root_path(root, WIKI_SOURCES_JSONL))


def append_wiki_source(root, *, month, slug, raw, fsync=False):
    """Append one source row. `raw` is the full line minus the leading '- '.
    Returns (True, None) or (False, reason)."""
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        return False, f"bad month {month!r} (want YYYY-MM)"
    raw = (raw or "").strip()
    if not raw:
        return False, "empty raw line"
    row = {"month": month, "slug": (slug or "").strip(), "raw": raw}
    _append_line(root_path(root, WIKI_SOURCES_JSONL), _dumps(row), fsync=fsync)
    return True, None


# ===========================================================================
# CLI: the manual entry points a skill calls -- wiki-triage's recap append and
# a source row. (ingest/distill append their own rows in-process.)
# ===========================================================================

def _cli(argv=None):
    import argparse

    p = argparse.ArgumentParser(description="append-only stores the wiki flows own")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("append-log", help="append one row to wiki/metadata/log.jsonl")
    a.add_argument("--date", required=True, help="YYYY-MM-DD")
    a.add_argument("--op", required=True, help="operation, e.g. triage")
    a.add_argument("--detail", required=True, help="one-line recap")
    a.add_argument("--root", default=None,
                   help="repo root that holds wiki/ (default: this script's repo)")
    s = sub.add_parser("append-source",
                       help="append one row to wiki/metadata/sources.jsonl")
    s.add_argument("--month", required=True, help="YYYY-MM")
    s.add_argument("--slug", required=True, help="source-page slug")
    s.add_argument("--raw", required=True, help="index line for the source")
    s.add_argument("--root", default=None,
                   help="repo root that holds wiki/ (default: this script's repo)")
    args = p.parse_args(argv)

    # Default to the repo this script lives in, so a row lands in the real wiki
    # no matter what cwd (a worktree, a subdir) it runs from.
    root = args.root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.cmd == "append-log":
        ok, why = append_wiki_log(root, date=args.date, op=args.op,
                                  detail=args.detail)
        if not ok:
            print(f"refused: {why}")
            return 1
        print(f"logged: {args.date} {args.op}")
        return 0
    if args.cmd == "append-source":
        ok, why = append_wiki_source(root, month=args.month, slug=args.slug,
                                     raw=args.raw)
        if not ok:
            print(f"refused: {why}")
            return 1
        print(f"logged: {args.month} {args.slug}")
        return 0
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli())
