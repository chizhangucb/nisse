#!/usr/bin/env python3
"""Stop-hook: keep the hub's records/sessions.jsonl complete.

Fires at the end of every turn (Stop), in the hub cwd and in every registered
satellite cwd. Always writes the HUB ledger. Idempotent upsert:
- If the current session's UUID already has a row, refresh its timestamp (so the
  time drifts toward last activity ~= session end) and keep the focus untouched.
- If not, insert a new row with a (pending) focus.

The ledger is records/sessions.jsonl. The upsert + its flock + the merge-by-row
guard all live in scripts/aios_ledger.upsert_session; this hook only resolves
(hub, repo) and calls it. The one scripts/ import (aios_ledger) is the sanctioned
exception to the "hooks import nothing" rule.

Hub + repo resolution (_resolve_hub_and_repo):
- Find the hub first (AIOS_HUB, else this hook's own repo via __file__). If it is
  a DIFFERENT repo that lists cwd as a registered satellite, the session ran in a
  satellite -> tag the row with that satellite's name (this catches a hub-shaped
  satellite like nisse that has its own records/ but should still ledger to the
  hub).
- Else if cwd holds the hub ledger -> cwd is the hub, repo `hub`.
- Else match realpath(cwd) to a Satellites-table Repo path and tag its name.
Unregistered cwd, or no reachable hub ledger -> silent no-op.
"""
import sys, json, datetime, os, re

_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def _is_subsession():
    """True if this Stop fired inside a machine-spawned headless `claude -p`
    sub-session, which must never touch the hub ledger. Pattern-matched (any
    `AIOS_*SUBSESSION` var, plus AIOS_HEADLESS_PROBE): the single skip contract
    every hook shares."""
    e = os.environ
    if e.get("AIOS_HEADLESS_PROBE"):
        return True
    return any(k.startswith("AIOS_") and k.endswith("SUBSESSION") for k in e)


# The hub ledger file: its presence marks a repo as the hub.
LEDGER_REL = os.path.join("records", "sessions.jsonl")


def _has_ledger(root):
    return os.path.exists(os.path.join(root, LEDGER_REL))


def main():
    # Throwaway headless spawns are skipped by explicit env flag.
    if _is_subsession():
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

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")
    try:
        import aios_ledger
        # Insert or refresh under the flock; focus=None keeps an existing focus
        # and inserts (pending) for a new row. blocking=False fails open on a
        # stuck lock so the 10s Stop budget is never blown; the merge-by-row
        # guard + genesis backstop recover a rare lost update.
        aios_ledger.upsert_session(hub, session=sid, stamp=stamp, repo=repo,
                                   blocking=False)
    except Exception:
        return 0
    return 0


def _collapse_worktree(p):
    """Collapse a git-worktree cwd under <repo>/.claude/worktrees/<name> down to
    its parent repo root (a worktree session is the same repo as its parent)."""
    return re.sub(r"/\.claude/worktrees/[^/]+(?:/.*)?$", "", p) if p else p


def _resolve_hub_and_repo(cwd):
    """(hub_root, repo_name) for this session, or (None, None) to no-op."""
    cwd = _collapse_worktree(cwd)
    hub = _find_hub()
    if hub is not None and os.path.realpath(hub) != os.path.realpath(cwd):
        name = _satellite_name(hub, cwd)
        if name is not None:
            return hub, name
    if _has_ledger(cwd):
        return cwd, "hub"
    if hub is None:
        return None, None
    name = _satellite_name(hub, cwd)
    if name is None:
        return None, None
    return hub, name


def _find_hub():
    """The hub root: AIOS_HUB if it holds the ledger, else this hook's own repo
    (<hub>/.claude/hooks/session-ledger.py). None if neither has a ledger."""
    candidates = []
    env = os.environ.get("AIOS_HUB")
    if env:
        candidates.append(os.path.expanduser(env))
    candidates.append(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    for c in candidates:
        if _has_ledger(c):
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
    hygiene validates parses identically here."""
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


if __name__ == "__main__":
    sys.exit(main())
