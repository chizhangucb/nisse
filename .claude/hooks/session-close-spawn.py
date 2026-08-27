#!/usr/bin/env python3
"""SessionStart hook: spawn the detached session-close sweeper.

On every new session (startup/clear/resume) in the hub or a registered
satellite, launches scripts/session_close.py as a detached process
(start_new_session, output to a state-dir log) with AIOS_CLOSE_SUBSESSION=1
so the sweeper's own headless claude children skip every hook. The sweeper
fills (pending) ledger focus lines and appends clearly-decided decision
blocks; see the script's docstring.

Also surfaces, once, a one-line notice when the previous sweep auto-logged
cold-inferred decisions, so the owner can veto a wrong block.

Guards: env AIOS_CLOSE_SUBSESSION (no recursion: the sweeper's children carry
it). Any anomaly is a silent no-op.
"""
import sys, json, os, subprocess


def find_hub(cwd):
    # AIOS_HUB, then this hook's own repo (__file__), then cwd LAST. cwd-last so a
    # hub-shaped satellite (its own records/) running the hub's copy resolves to
    # the REAL hub, not itself; a standalone clone still self-resolves via __file__.
    candidates = []
    env = os.environ.get("AIOS_HUB")
    if env:
        candidates.append(os.path.expanduser(env))
    candidates.append(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    candidates.append(cwd)
    for c in candidates:
        # The hub marker is records/sessions.jsonl.
        if os.path.exists(os.path.join(c, "records", "sessions.jsonl")):
            return c
    return None


def surface_notice(state):
    """Print (once) what the last sweep auto-logged; stdout reaches the model."""
    path = os.path.join(state, "last-run.json")
    try:
        with open(path) as f:
            last = json.load(f)
    except (OSError, ValueError):
        return
    if last.get("noted") or not last.get("logged"):
        return
    for entry in last["logged"]:
        titles = ", ".join(t for t in entry.get("titles", []) if t) or "1 block"
        print(f"Session-close sweeper auto-logged to records/decisions.jsonl from "
              f"session {entry.get('session')}: {titles}. Tell the owner in one "
              f"line so they can veto a wrong block.")
    last["noted"] = True
    try:
        with open(path, "w") as f:
            json.dump(last, f, indent=2)
    except OSError:
        pass


def main():
    if os.environ.get("AIOS_CLOSE_SUBSESSION"):
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    sid = (data.get("session_id") or "").strip()
    cwd = (data.get("cwd") or "").strip()
    if not sid or not cwd:
        return 0
    hub = find_hub(cwd)
    if hub is None:
        return 0
    state = os.path.join(hub, ".claude", "state", "session-close")
    try:
        os.makedirs(state, exist_ok=True)
        surface_notice(state)
        log = open(os.path.join(state, "sweeper.log"), "a")
        subprocess.Popen(
            [sys.executable, os.path.join(hub, "scripts", "session_close.py"),
             "--current", sid],
            cwd=hub, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
            env=dict(os.environ, AIOS_CLOSE_SUBSESSION="1"))
        log.close()
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
