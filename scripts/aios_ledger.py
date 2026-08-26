#!/usr/bin/env python3
"""Append-only JSONL ledger storage for the AIOS (CHI-313).

The single sanctioned write path and shared read helper for the four ledgers
that used to be hand-maintained markdown and corrupted under concurrent
sessions on the shared worktree (CHI-299):

  records/decisions.jsonl        append-only, one row per decision BLOCK
  records/sessions.jsonl         upsert current-state store, one row per session
  wiki/metadata/log.jsonl        append-only, one row per wiki operation
  wiki/metadata/sources.jsonl    append-only, one row per meeting source

Design + reasoning: plans/2026-08-25-sqlite-ledger-storage.md (approved),
records/brainstorms/2026-08-25-sqlite-ledger-storage.md.

Append contract (the three true append-logs: decisions, wiki log, wiki sources)
--------------------------------------------------------------------------------
One writer at a time appends one whole line via a single os.write under an
flock (O_APPEND | O_CREAT), ensure_ascii=False. On a local single-writer-per-
file filesystem this removes the read-modify-write reorder race that caused
CHI-299. This is NOT a bare "the OS makes it atomic" claim: Python buffered
writes are not one syscall and a crash mid-append can truncate the last line,
so the flock + whole-line os.write + a reader that SKIPS any unparseable or
partial trailing line are all load-bearing. The invariant is void on NFS /
iCloud / Dropbox-synced paths.

Durability: appends are not fsync'd by default (an fsync-per-append is not
required because refs/ledger/checkpoints + the cross-machine spool are the
durability backstop). Pass fsync=True to force it.

sessions.jsonl is an UPSERT store, not an append-log: it refreshes every turn,
so it keeps a full read-modify-write under an flock (it was never the CHI-299
corruption source) and only its serialization changed from a markdown table to
JSONL so Varde reads structured data.

Bake: through the bake period every decisions/log/sources append ALSO mirror-
writes the retired markdown file (dual-write, so a revert is clean). The
markdown writer is dropped only after the bake. Because a single locked command
is now the only writer, the decision-log reorder Stop hook, the ledger order/
format hygiene backstops, log_rotate, and monthly sharding are all retired.
"""

import argparse
import datetime
import fcntl
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DECISIONS_JSONL = ("records", "decisions.jsonl")
DECISIONS_MD = ("records", "decisions.md")
SESSIONS_JSONL = ("records", "sessions.jsonl")
WIKI_LOG_JSONL = ("wiki", "metadata", "log.jsonl")
WIKI_SOURCES_JSONL = ("wiki", "metadata", "sources.jsonl")

# Lock siblings. The append-logs each guard on their own <file>.lock; sessions
# keeps the historical .sessions_index.lock name so a concurrent old-code writer
# during a partial revert still serializes against us.
SESSIONS_LOCKFILE = ".sessions_index.lock"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Same header shape session_close.py / the decision-log hook validate. The id
# class accepts hyphens so a full hyphenated UUID validates as well as a legacy
# 8-char short (CHI-264).
DECISION_HEADER_RE = re.compile(
    r"^## \d{4}-\d{2}-\d{2}: .+ \(session [0-9A-Za-z-]+, stream: [^)]+\)$")
EM_DASH = "\u2014"  # em dash codepoint, banned in anything Chi reads


def hub_path(hub, parts):
    return os.path.join(hub, *parts)


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
    the diff; field order is the dict's insertion order (kept stable by the
    builders below) for a legible git diff, so no sort_keys."""
    return json.dumps(row, ensure_ascii=False) + "\n"


def read_rows(path):
    """Every well-formed row in a JSONL ledger, in file (append) order.

    Skips blank lines and any line that does not parse as a JSON object,
    including a truncated trailing line from a crash mid-append (the tolerant-
    reader half of the append contract). Missing file -> []."""
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


# ---------------------------------------------------------------------------
# id matching (shared contract, mirrors scripts/ledger_ids.py)
# ---------------------------------------------------------------------------

def _strip_id(v):
    return (v or "").strip().rstrip("…").strip()


def id_match(stored, live):
    """True if a stored id refers to the live full session id: exact, or a
    shorter stored id that strictly prefixes live. Mirrors ledger_ids.id_match
    so mixed full-UUID / legacy-short ids coexist (CHI-264)."""
    stored = _strip_id(stored)
    live = _strip_id(live)
    if not stored or not live:
        return False
    return stored == live or (len(stored) < len(live) and live.startswith(stored))


# ===========================================================================
# Decisions (append-only, one row per block)
# ===========================================================================
#
# Row schema:
#   {"date": "YYYY-MM-DD", "title": str,
#    "session": str|null, "stream": str|null, "body": str}
# body is the verbatim markdown between the header and the next block (bullets
# and any `>` supersede notes), trailing/leading blank lines trimmed. Legacy
# history blocks with no attribution carry session=null, stream=null.

def read_decisions(hub):
    """All decision blocks, chronological (append order, oldest first)."""
    return read_rows(hub_path(hub, DECISIONS_JSONL))


def session_has_decision_block(hub, sid):
    """True when decisions.jsonl already carries a block for this session
    (warm). Prefix-tolerant both ways (CHI-264). Replaces session_close's
    has_own_block markdown scan."""
    for row in read_decisions(hub):
        token = row.get("session")
        if token and (id_match(token, sid) or id_match(sid, token)):
            return True
    return False


def _decision_pair_present(hub, session, stream):
    """True when a block for exactly this (session, stream) already exists.
    The one-block-per-(session,stream) idempotency key (CHI-313 review 4);
    replaces the has_own_block guard for the append path."""
    for row in read_decisions(hub):
        if row.get("session") == session and row.get("stream") == stream:
            return True
    return False


def validate_decision(*, date, title, session, stream, body):
    """Return None if valid, else a reason string. Enforces the header shape,
    the bullet/`>`-note body shape, and the em-dash ban."""
    if not DATE_RE.match(date or ""):
        return f"bad date {date!r} (want YYYY-MM-DD)"
    title = (title or "").strip()
    if not title:
        return "empty title"
    if not (session or "").strip():
        return "empty session id"
    if not (stream or "").strip():
        return "empty stream"
    header = f"## {date}: {title} (session {session}, stream: {stream})"
    if not DECISION_HEADER_RE.match(header):
        return f"header fails format: {header!r}"
    body = (body or "").strip()
    if not body:
        return "empty body"
    for ln in body.splitlines():
        s = ln.strip()
        if s == "" or s.startswith("- **") or s.startswith("- Decision:") \
                or s.startswith(">"):
            continue
        return f"body line is not a bullet or note: {ln!r}"
    if EM_DASH in header or EM_DASH in body:
        return "em dash banned in anything Chi reads"
    return None


def render_decision_block(row):
    """One decision block as markdown text (no trailing newline).

    Attributed: `## date: title (session s, stream: st)` + blank + body.
    Legacy (session/stream null): `## date: title` + blank + body."""
    date = row["date"]
    title = row["title"]
    session = row.get("session")
    stream = row.get("stream")
    body = (row.get("body") or "").rstrip("\n")
    if session and stream:
        header = f"## {date}: {title} (session {session}, stream: {stream})"
    else:
        header = f"## {date}: {title}"
    return f"{header}\n\n{body}"


def append_decision(hub, *, date, title, session, stream, body,
                    dual_write_md=True, fsync=False):
    """Validate and append one decision block. Returns (True, None) on write,
    (False, reason) on refusal.

    Idempotency (CHI-313 review 4): refuses if a block for this exact
    (session, stream) already exists, so a warm session's own block plus the
    session-close sweeper's append can never duplicate (this replaces the old
    has_own_block guard at the write layer).

    Through the bake, also inserts the rendered block at the TOP of
    decisions.md (dual-write) so a code revert leaves the markdown current.
    Because this locked command is the only writer, the block lands at the
    correct newest-first position without the retired reorder Stop hook."""
    reason = validate_decision(date=date, title=title, session=session,
                               stream=stream, body=body)
    if reason:
        return False, reason
    if _decision_pair_present(hub, session, stream):
        return False, f"block already exists for session {session} stream {stream}"
    body = body.strip()
    row = {"date": date, "title": title.strip(),
           "session": session, "stream": stream, "body": body}
    _append_line(hub_path(hub, DECISIONS_JSONL), _dumps(row), fsync=fsync)
    if dual_write_md:
        _mirror_insert_decision_md(hub, row)
    return True, None


def _mirror_insert_decision_md(hub, row):
    """Insert one rendered block as the newest entry in decisions.md, above the
    first `## ` block (so the header + rotated-history section stay on top).
    Bake-only mirror; best-effort (never breaks the jsonl append that already
    landed)."""
    path = hub_path(hub, DECISIONS_MD)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return
    block = render_decision_block(row)
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("## ")),
               len(lines))
    lines[idx:idx] = block.splitlines() + [""]
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip("\n") + "\n")
        os.replace(tmp, path)
    except OSError:
        pass


# ===========================================================================
# Sessions (UPSERT current-state store, one row per session, keeps its flock)
# ===========================================================================
#
# Row schema: {"stamp": "YYYY-MM-DD HHMM", "session": str,
#              "focus": str, "repo": str}
# stamp/session/focus/repo mirror the four markdown columns. focus "(pending)"
# is the placeholder the session-close sweeper later fills.

FOCUS_WORD_CAP = 15
PENDING = "(pending)"
UNKNOWN_TIME = "0001-01-01 0001"


def _sessions_lock_path(hub):
    return os.path.join(hub, "records", SESSIONS_LOCKFILE)


class _SessionsLock:
    """Blocking exclusive flock across a sessions.jsonl read-modify-write.
    Fail-open: if the lockfile cannot be opened at all, proceed unlocked (a
    rare race beats never writing). Mirrors scripts/ledger_lock semantics."""

    def __init__(self, hub, blocking=True, retry_seconds=2.0):
        self.path = _sessions_lock_path(hub)
        self.blocking = blocking
        self.retry_seconds = retry_seconds
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        except OSError:
            self.fd = None
            return False
        if self.blocking:
            fcntl.flock(self.fd, fcntl.LOCK_EX)
            return True
        import time
        deadline = time.monotonic() + self.retry_seconds
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(self.fd)
        return False


def read_sessions(hub):
    """Current session rows, newest-first by stamp (the ledger's contract)."""
    rows = read_rows(hub_path(hub, SESSIONS_JSONL))
    return _sort_sessions(rows)


def _sort_sessions(rows):
    def key(r):
        try:
            return datetime.datetime.strptime(r.get("stamp", ""), "%Y-%m-%d %H%M")
        except ValueError:
            return datetime.datetime.min
    return sorted(rows, key=key, reverse=True)


def session_ids(hub):
    return {_strip_id(r.get("session")) for r in read_sessions(hub)}


def pending_sessions(hub):
    """[(stamp, session, repo)] for every (pending) row."""
    return [(r.get("stamp"), _strip_id(r.get("session")), r.get("repo"))
            for r in read_sessions(hub) if r.get("focus") == PENDING]


def _cap_focus(text):
    words = (text or "").split()
    if len(words) <= FOCUS_WORD_CAP:
        return text
    return " ".join(words[:FOCUS_WORD_CAP]) + "…"


def _write_sessions(hub, rows):
    """Atomic replace of the whole store (temp + os.replace). Caller holds the
    lock; this only guards against a concurrent reader seeing a torn file."""
    path = hub_path(hub, SESSIONS_JSONL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in _sort_sessions(rows):
            f.write(_dumps(r))
    os.replace(tmp, path)


def upsert_session(hub, *, session, stamp, repo, focus=None, blocking=True,
                   retry_seconds=2.0):
    """Insert or refresh this session's row under the lock.

    If a row exists (matched by id_match, so a legacy short cell resolves to
    this full id and is upgraded in place), refresh its stamp and, when focus
    is given, its focus (capped); otherwise keep the existing focus. If absent,
    insert with focus or (pending). Refuses a write that would DROP any row it
    read (the merge-by-row guard, CHI-193). Returns True on write.

    blocking=False makes the lock fail-open after retry_seconds (proceed
    unlocked rather than block): the Stop hook uses this so a stuck lock never
    blows its budget, relying on the merge-by-row guard + genesis backstop to
    recover a rare lost update, exactly as the old markdown hook did."""
    with _SessionsLock(hub, blocking=blocking, retry_seconds=retry_seconds):
        rows = read_rows(hub_path(hub, SESSIONS_JSONL))
        before = {_strip_id(r.get("session")) for r in rows}
        migrated_from = None
        found = False
        for r in rows:
            if id_match(r.get("session"), session):
                if _strip_id(r.get("session")) != session:
                    migrated_from = _strip_id(r.get("session"))
                    r["session"] = session
                r["stamp"] = stamp
                if focus is not None:
                    r["focus"] = _cap_focus(focus)
                found = True
                break
        if not found:
            rows.append({"stamp": stamp, "session": session,
                         "focus": _cap_focus(focus) if focus else PENDING,
                         "repo": repo})
        after = {_strip_id(r.get("session")) for r in rows}
        expected = before - ({migrated_from} if migrated_from else set())
        if not after >= expected:
            return False
        _write_sessions(hub, rows)
    return True


def insert_pending_if_absent(hub, *, session, stamp, repo):
    """Insert a (pending) row only if no row for this session exists yet, under
    the lock. Returns True if inserted. The CHI-158 genesis backstop wants
    insert-only semantics (never bump an existing row's stamp), and the under-
    lock re-check makes a concurrent late Stop hook unable to duplicate it."""
    with _SessionsLock(hub):
        rows = read_rows(hub_path(hub, SESSIONS_JSONL))
        if any(id_match(r.get("session"), session) for r in rows):
            return False
        rows.append({"stamp": stamp, "session": session,
                     "focus": PENDING, "repo": repo})
        _write_sessions(hub, rows)
    return True


def set_focus(hub, session, focus):
    """Fill this session's (pending) focus, found by id, under the lock. Only
    touches a still-pending row (idempotent, safe against a live Stop hook).
    Returns True if a pending row was filled."""
    with _SessionsLock(hub):
        rows = read_rows(hub_path(hub, SESSIONS_JSONL))
        for r in rows:
            if id_match(r.get("session"), session) and r.get("focus") == PENDING:
                r["focus"] = _cap_focus(focus)
                _write_sessions(hub, rows)
                return True
    return False


# ===========================================================================
# Wiki log (append-only)  row: {"date","op","detail"}
# ===========================================================================

def read_wiki_log(hub):
    return read_rows(hub_path(hub, WIKI_LOG_JSONL))


def append_wiki_log(hub, *, date, op, detail, fsync=False):
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
    _append_line(hub_path(hub, WIKI_LOG_JSONL), _dumps(row), fsync=fsync)
    return True, None


# ===========================================================================
# Wiki sources (append-only)  row: {"month","slug","raw", ...structured}
# ===========================================================================
#
# The legacy monthly shards are wildly irregular (3-7 pipe fields, tags either
# in a 5th column or embedded as [tag] in the annotation, `| ledger |` lines
# with no [[slug]]). To be lossless the row always carries `raw` = the original
# line content after the leading "- ". New appends supply the same formatted
# line plus month + slug; readers can re-parse `raw` if they need fields.

def read_wiki_sources(hub):
    return read_rows(hub_path(hub, WIKI_SOURCES_JSONL))


def append_wiki_source(hub, *, month, slug, raw, fsync=False):
    """Append one source row. `raw` is the full line minus the leading '- '.
    Returns (True, None) or (False, reason)."""
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        return False, f"bad month {month!r} (want YYYY-MM)"
    raw = (raw or "").strip()
    if not raw:
        return False, "empty raw line"
    row = {"month": month, "slug": (slug or "").strip(), "raw": raw}
    _append_line(hub_path(hub, WIKI_SOURCES_JSONL), _dumps(row), fsync=fsync)
    return True, None


# ---------------------------------------------------------------------------
# CLI: the sanctioned write path the deny hook points agents at
# ---------------------------------------------------------------------------

def _find_hub(cli_hub):
    if cli_hub:
        return os.path.abspath(os.path.expanduser(cli_hub))
    env = os.environ.get("AIOS_HUB")
    if env and os.path.exists(os.path.join(os.path.expanduser(env), "records")):
        return os.path.abspath(os.path.expanduser(env))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_body(args):
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            return f.read()
    return args.body or ""


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Append-only JSONL ledger writer (CHI-313). "
                    "The only sanctioned write path for the four ledgers.")
    ap.add_argument("--hub", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("append-decision",
                       help="append one decision block to decisions.jsonl")
    d.add_argument("--date", required=True)
    d.add_argument("--title", required=True)
    d.add_argument("--session", required=True)
    d.add_argument("--stream", required=True)
    d.add_argument("--body", default=None,
                   help="block body (bullets/notes); or use --body-file")
    d.add_argument("--body-file", default=None)
    d.add_argument("--no-md", action="store_true",
                   help="skip the bake-period decisions.md mirror write")

    lg = sub.add_parser("append-log", help="append one wiki-log row")
    lg.add_argument("--date", required=True)
    lg.add_argument("--op", required=True)
    lg.add_argument("--detail", required=True)

    sc = sub.add_parser("append-source", help="append one wiki-source row")
    sc.add_argument("--month", required=True)
    sc.add_argument("--slug", default="")
    sc.add_argument("--raw", required=True)

    us = sub.add_parser("upsert-session", help="insert/refresh a sessions row")
    us.add_argument("--session", required=True)
    us.add_argument("--stamp", required=True)
    us.add_argument("--repo", required=True)
    us.add_argument("--focus", default=None)

    args = ap.parse_args(argv)
    hub = _find_hub(args.hub)

    if args.cmd == "append-decision":
        ok, reason = append_decision(
            hub, date=args.date, title=args.title, session=args.session,
            stream=args.stream, body=_read_body(args),
            dual_write_md=not args.no_md)
    elif args.cmd == "append-log":
        ok, reason = append_wiki_log(hub, date=args.date, op=args.op,
                                     detail=args.detail)
    elif args.cmd == "append-source":
        ok, reason = append_wiki_source(hub, month=args.month, slug=args.slug,
                                        raw=args.raw)
    elif args.cmd == "upsert-session":
        ok = upsert_session(hub, session=args.session, stamp=args.stamp,
                            repo=args.repo, focus=args.focus)
        reason = None if ok else "merge-by-row guard refused the write"
    else:  # pragma: no cover
        ap.error(f"unknown command {args.cmd}")
        return 2

    if not ok:
        sys.stderr.write(f"refused: {reason}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
