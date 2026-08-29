#!/usr/bin/env python3
"""Satellite daily-digest emitter (hub spool writer).

Writes one small JSON artifact per run into the hub's
`records/spool/nisse/` directory so this repo's daily maintenance run folds
into the hub's one fleet digest instead of Chi watching a separate channel
for every satellite (governance/satellite-repos.md "Daily-report spool",
hub `scripts/satellite_digest.py`).

This module DUPLICATES the hub's tiny `write_artifact()` writer rather than
importing it -- satellite runtime code reads the hub read-only and never
imports hub code (boundary invariant, governance/satellite-repos.md). It is
otherwise a normal repo-local script: no network, no auth, no secrets, and
every signal degrades gracefully instead of raising, so a git hiccup here
never sinks the rest of a daily-maintenance run.

Artifact contract (must match the hub schema exactly):
    {"repo": "nisse", "date": "YYYY-MM-DD",
     "needs_you": [<floor-class line>, ...],   # rare, usually []
     "auto_done": {<category>: <int count>, ...},
     "health": [<one-line status note>, ...]}  # always >= 1 line

Hub path resolution: env AIOS_HUB if set and non-empty, else
~/chizhang-2 -- the sanctioned public hub-resolution seam, never hardcoded.

Scheduling: nisse has no daily job wired on this machine yet. Wiring one
(launchd/cron) is a separate, Chi-gated step; this module only adds the
stage + a standalone entrypoint for it to call.

Usage:
    python3 scripts/emit_daily_digest.py                  # write + print path
    python3 scripts/emit_daily_digest.py --root <repo> --hub <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import date

REPO_NAME = "nisse"


# ---------------------------------------------------------------------------
# Hub writer (duplicated from hub scripts/satellite_digest.py -- do not
# import hub code from a satellite; ~15 lines, cheap to keep in sync)
# ---------------------------------------------------------------------------

def write_artifact(hub, repo, date_str, needs_you, auto_done, health):
    d = os.path.join(hub, "records", "spool", repo)
    os.makedirs(d, exist_ok=True)
    payload = {"repo": repo, "date": date_str,
               "needs_you": list(needs_you or []), "auto_done": dict(auto_done or {}),
               "health": list(health or [])}
    path = os.path.join(d, f"{date_str}-{uuid.uuid4().hex[:8]}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)
    return path


def resolve_hub():
    env = os.environ.get("AIOS_HUB")
    if env:
        return os.path.expanduser(env)
    return os.path.expanduser("~/chizhang-2")


# ---------------------------------------------------------------------------
# Derivation: cheap, local git signals only -- no network, no auth, no
# secrets, never raises (a failed `git` call just degrades the signal).
# ---------------------------------------------------------------------------

def _git(root, args):
    try:
        p = subprocess.run(["git", "-C", root] + args, capture_output=True,
                           text=True, timeout=5)
        return p.returncode, p.stdout.strip()
    except Exception:  # noqa: BLE001  a signal must never crash the emitter
        return 1, ""


def git_signals(root):
    """Current branch, uncommitted file count, commits in the last 24h, and
    unpushed-vs-upstream count for the repo at `root`. Any signal that can't
    be read (not a git repo, no upstream, git missing) degrades to a safe
    default instead of raising."""
    branch = None
    rc, out = _git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if rc == 0 and out:
        branch = out

    uncommitted = 0
    rc, out = _git(root, ["status", "--porcelain"])
    if rc == 0:
        uncommitted = len([ln for ln in out.splitlines() if ln.strip()])

    commits_24h = 0
    rc, out = _git(root, ["log", "--since=24 hours ago", "--oneline"])
    if rc == 0:
        commits_24h = len([ln for ln in out.splitlines() if ln.strip()])

    unpushed = None
    rc, out = _git(root, ["rev-list", "--count", "@{u}..HEAD"])
    if rc == 0 and out.isdigit():
        unpushed = int(out)

    return {"branch": branch, "uncommitted": uncommitted,
            "commits_24h": commits_24h, "unpushed": unpushed}


def build_payload(root):
    """git_signals() -> (needs_you, auto_done, health). Pure mapping, no IO
    beyond the git_signals() call itself."""
    sig = git_signals(root)
    health = []

    if sig["branch"]:
        health.append(f"branch: {sig['branch']}")
    else:
        health.append("branch: unknown (not a git repo or git unavailable)")

    if sig["uncommitted"]:
        health.append(f"{sig['uncommitted']} uncommitted file(s)")
    else:
        health.append("working tree clean")

    if sig["unpushed"] is None:
        health.append("no upstream tracking branch")
    elif sig["unpushed"] > 0:
        health.append(f"{sig['unpushed']} unpushed commit(s)")
    else:
        health.append("up to date with upstream")

    auto_done = {"commits": sig["commits_24h"]}
    needs_you = []  # floor-class only; this emitter has no floor detection
    return needs_you, auto_done, health


# ---------------------------------------------------------------------------
# Emit
# ---------------------------------------------------------------------------

def emit(root, hub=None, date_str=None, repo=REPO_NAME):
    """Derive signals from the repo at `root` and write one artifact into
    <hub>/records/spool/<repo>/. Returns the artifact path."""
    hub = hub or resolve_hub()
    date_str = date_str or date.today().isoformat()
    needs_you, auto_done, health = build_payload(root)
    return write_artifact(hub, repo, date_str, needs_you, auto_done, health)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.getcwd(),
                    help="repo to derive git signals from (default: cwd)")
    ap.add_argument("--hub", default=None,
                    help="override hub path (default: AIOS_HUB or ~/chizhang-2)")
    ap.add_argument("--repo", default=REPO_NAME)
    ap.add_argument("--date", default=None, help="override date (YYYY-MM-DD)")
    args = ap.parse_args(argv)
    path = emit(args.root, hub=args.hub, date_str=args.date, repo=args.repo)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
