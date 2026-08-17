#!/usr/bin/env python3
"""Stop hook: keep the hub's records/sessions_index.md complete.

Fires at the end of every turn (Stop), in the hub cwd and in every registered
satellite cwd. Always writes the HUB ledger. Idempotent upsert:
- If the current session's UUID already has a row, refresh its timestamp cell
  (so the time drifts toward last activity ~= session end) and keep the
  hand-written focus untouched, except trimming it to the word cap.
- If not, insert a new row at the top of the table with a (pending) focus.

Table contract: 4 columns (Date, Session ID, Focus, Repo), Focus capped at
FOCUS_WORD_CAP words. The Repo cell is `hub` when the session ran in the hub
cwd, else the satellite's name from operations.md `## Satellites`.

Hub + repo resolution (_resolve_hub_and_repo):
- Case A: cwd holds records/sessions_index.md -> cwd is the hub, repo `hub`.
- Case B: else the session ran in a satellite. Find the hub (AIOS_HUB, else
  this hook's own repo via __file__), match realpath(cwd) to a Satellites-table
  Repo path, and tag the row with that satellite's name.
Unregistered cwd, or no reachable hub ledger -> silent no-op, so stray repos
never pollute the ledger. Never duplicates rows.
"""
import sys, json, datetime, os, re, fcntl, time

FOCUS_WORD_CAP = 15
LEDGER_LOCKFILE = ".sessions_index.lock"
# Parseable stand-in for a row whose real time is unknown, so a resort keyed on
# the time cell never sinks it. No path emits it today; any future insert
# without a known time uses this, never a dashes placeholder.
UNKNOWN_TIME = "0001-01-01 0001"

def main():
    # Throwaway headless spawns are skipped by explicit env flag, never by
    # guessing from the transcript: the close sweeper's own children set
    # AIOS_CLOSE_SUBSESSION; ad-hoc probes and one-off analyses set
    # AIOS_HEADLESS_PROBE. Everything else is a real session and gets a row
    # (fail-open: heuristics on prompt source drop real work).
    if os.environ.get("AIOS_CLOSE_SUBSESSION") or \
            os.environ.get("AIOS_HEADLESS_PROBE"):
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    sid = (data.get("session_id") or "").strip()
    cwd = (data.get("cwd") or "").strip()
    if not sid or not cwd:
        return 0

    hub, repo = _resolve_hub_and_repo(cwd)
    if hub is None:
        return 0

    ledger = f"{hub}/records/sessions_index.md"
    # The ledger is one shared file every session's Stop hook and the close
    # sweeper read-modify-write. Hold an flock across the whole critical
    # section so concurrent writes cannot drop each other's rows. Fail-open on
    # a stuck lock: better a rare race than blowing the 10s hook budget.
    # Mirrors scripts/ledger_lock.py; kept inline so the hook imports nothing.
    lock_fd = _acquire_lock(ledger)
    try:
        try:
            with open(ledger) as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            return 0

        short = sid[:8]
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")

        # find the header separator row (the |---|---|...| line)
        sep = next((i for i, ln in enumerate(lines)
                    if ln.lstrip().startswith("|") and set(ln.replace("|", "").strip()) <= {"-", " "}
                    and "-" in ln), None)
        if sep is None:
            return 0

        # Merge-by-row guard: snapshot the ids present before touching the
        # table. The hook only ever adds or updates its OWN row, never removes
        # one, so the id set it writes must stay a superset of what it read. A
        # shrink means a parse or corruption bug: refuse the write rather than
        # clobber other sessions' rows.
        before_ids = _row_ids(lines, sep)

        # look for an existing row for this session
        found = False
        for i in range(sep + 1, len(lines)):
            ln = lines[i]
            if not ln.lstrip().startswith("|"):
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[1].startswith(short):
                cells[0] = stamp
                cells[2] = _cap_focus(cells[2])
                lines[i] = "| " + " | ".join(cells) + " |"
                found = True
                break

        if not found:
            lines.insert(sep + 1, f"| {stamp} | {short}… | (pending) | {repo} |")

        _resort(lines, sep)
        # Refuse a write that would drop any row we read (see before_ids above).
        if not _row_ids(lines, sep) >= before_ids:
            return 0
        _write(ledger, lines)
    finally:
        _release_lock(lock_fd)
    return 0


def _acquire_lock(ledger, retry_seconds=2.0):
    """Non-blocking flock on the ledger's sibling lockfile; fail-open.

    Returns the held fd, or None if the lock could not be taken within
    retry_seconds (caller then proceeds unlocked, never past its budget)."""
    path = os.path.join(os.path.dirname(ledger), LEDGER_LOCKFILE)
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None
    deadline = time.monotonic() + retry_seconds
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.05)


def _release_lock(fd):
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

def _row_ids(lines, sep):
    """Set of session short-ids in the table below sep: cells[1] with a trailing
    ellipsis stripped. Feeds the merge-by-row guard; mirrors the upsert loop's
    cell parsing so what it counts is exactly what the write would carry."""
    ids = set()
    for i in range(sep + 1, len(lines)):
        ln = lines[i]
        if not ln.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) >= 2:
            ids.add(cells[1].rstrip("…").strip())
    return ids

def _collapse_worktree(p):
    """Collapse a git-worktree cwd under <repo>/.claude/worktrees/<name> down to
    its parent repo root. A worktree session is the same repo as its parent, so
    a hub-worktree session must resolve to the primary hub (not the worktree's
    private ledger copy) and a satellite-worktree session must realpath-match
    its registered parent. Scoped to the .claude/worktrees/ convention only."""
    return re.sub(r"/\.claude/worktrees/[^/]+(?:/.*)?$", "", p) if p else p

def _resolve_hub_and_repo(cwd):
    """(hub_root, repo_name) for this session, or (None, None) to no-op.

    Case A: cwd is the hub itself (holds records/sessions_index.md) -> `hub`.
    Case B: cwd is a registered satellite -> resolve the hub and map cwd to its
    Satellites-table name. Unregistered cwd or no reachable hub -> (None, None)."""
    cwd = _collapse_worktree(cwd)
    if os.path.exists(os.path.join(cwd, "records", "sessions_index.md")):
        return cwd, "hub"
    hub = _find_hub()
    if hub is None:
        return None, None
    name = _satellite_name(hub, cwd)
    if name is None:
        return None, None
    return hub, name

def _find_hub():
    """The hub root: AIOS_HUB if it holds the ledger, else this hook's own repo
    (the hook lives at <hub>/.claude/hooks/session-ledger.py). None if neither
    has a ledger."""
    candidates = []
    env = os.environ.get("AIOS_HUB")
    if env:
        candidates.append(os.path.expanduser(env))
    candidates.append(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    for c in candidates:
        if os.path.exists(os.path.join(c, "records", "sessions_index.md")):
            return c
    return None

def _satellite_name(hub, cwd):
    """Name of the registered satellite whose Repo path resolves to cwd, from the
    hub's operations.md `## Satellites` table. None if cwd matches no row."""
    try:
        with open(os.path.join(hub, "operations.md")) as f:
            text = f.read()
    except OSError:
        return None
    target = os.path.realpath(cwd)
    for row in _parse_satellites(text):
        raw = row.get("Repo path", "").strip().strip("`")
        if raw and os.path.realpath(os.path.expanduser(raw)) == target:
            return (row.get("Satellite", "") or "").strip() or None
    return None

def _parse_satellites(text):
    """Rows (dicts keyed by header) of the first markdown table under the
    `## Satellites` heading. Mirrors scripts/hygiene_check.py so a table that
    hygiene validates parses identically here; the hook stays self-contained."""
    m = re.search(r"(?m)^## Satellites[^\n]*\n", text)
    if not m:
        return []
    rest = text[m.end():]
    nxt = re.search(r"(?m)^#{1,6} ", rest)
    body = rest[:nxt.start()] if nxt else rest
    header, rows = None, []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        if header is None:
            header = cells
            continue
        rows.append(dict(zip(header, cells)))
    return rows

def _cap_focus(text):
    """Trim a focus cell to FOCUS_WORD_CAP words, marking the cut with an
    ellipsis. Leaves (pending) and already-short cells untouched."""
    words = text.split()
    if len(words) <= FOCUS_WORD_CAP:
        return text
    return " ".join(words[:FOCUS_WORD_CAP]) + "…"

def _resort(lines, sep):
    """Keep the ledger's newest-first contract: sort the contiguous table
    rows below the separator by their timestamp cell, descending."""
    start = sep + 1
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    rows = lines[start:end]
    def key(ln):
        first = ln.strip().strip("|").split("|")[0].strip()
        try:
            return datetime.datetime.strptime(first, "%Y-%m-%d %H%M")
        except ValueError:
            return datetime.datetime.min  # unparsable rows sink to the bottom
    rows.sort(key=key, reverse=True)
    lines[start:end] = rows

def _write(path, lines):
    # temp + os.replace so a concurrent reader never sees a half-written table
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)

if __name__ == "__main__":
    sys.exit(main())
