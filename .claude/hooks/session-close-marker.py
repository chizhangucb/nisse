#!/usr/bin/env python3
"""SessionEnd hook: drop a done-marker for this session.

Fires on graceful exits only (/clear, /logout, /exit, Ctrl+D, normal app
shutdown). Writes one empty file named after the session id under
<hub>/.claude/state/session-close/done/. That marker is the positive
"this session is over, safe to summarize" signal the SessionStart sweeper
uses; hard kills never fire SessionEnd and fall back to the 24h staleness
rule instead. Nothing else happens here: no summarizing, no child process.

Registered in the hub and in every satellite (template:
governance/satellite-repos.md). Any anomaly is a silent no-op.
"""
import sys, json, os


def find_hub(cwd):
    # AIOS_HUB, then this hook's own repo (__file__), then cwd LAST. cwd-last so a
    # hub-shaped satellite (its own records/, e.g. nisse) running the hub's copy
    # resolves to the REAL hub, not itself (CHI-289); a standalone clone still
    # self-resolves via __file__.
    candidates = []
    env = os.environ.get("AIOS_HUB")
    if env:
        candidates.append(os.path.expanduser(env))
    # This file lives at <hub>/.claude/hooks/, so its own repo is a candidate.
    candidates.append(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    candidates.append(cwd)
    for c in candidates:
        # The hub marker is now records/sessions.jsonl; accept the legacy
        # sessions_index.md too so hub-detection works through the bake.
        if os.path.exists(os.path.join(c, "records", "sessions.jsonl")) \
                or os.path.exists(os.path.join(c, "records", "sessions_index.md")):
            return c
    return None


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
    done = os.path.join(hub, ".claude", "state", "session-close", "done")
    try:
        os.makedirs(done, exist_ok=True)
        with open(os.path.join(done, sid), "w"):
            pass
    except OSError:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
