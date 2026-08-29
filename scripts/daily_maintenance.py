#!/usr/bin/env python3
"""Example: a merged daily-maintenance orchestrator (DORMANT).

This is a worked example, not a script that ships live. Nothing schedules it
(operations.md Scheduled tasks starts empty; see its note). It shows the
pattern for combining several deterministic morning checks into ONE digest
and sending it once, instead of one launchd/cron job per check spamming your
notifications separately.

The pattern: each check runs as an isolated "stage" (a failure in one stage
is caught and reported, never sinks the others), stages assemble into one
digest, the digest sends through a single gated notification path
(scripts/egress_gate/egress.py's `tracker-ping` verb -- reuses the same path
scripts/ticket_tracker.py uses for its own ping).

Stages wired here (the first two are dormant tier-2/tier-3 pieces you may
not have configured yet, so an unconfigured stage is reported as skipped,
not failed):
  - hygiene: scripts/hygiene_check.py's findings, counted by severity.
  - tracker drift: scripts/ticket_tracker.py --sweep (only if
    NISSE_TRACKER_DRIFT=1 and TICKET_TRACKER_PROJECTS is set).
  - daily digest: scripts/emit_daily_digest.py writes one small JSON
    artifact into the hub's records/spool/nisse/ so this repo's run folds
    into the hub's fleet digest instead of a separate channel. Local-only
    (git signals), never blocked by hub/network availability.

Adapt this by adding your own stage_*(root) function that returns a Stage,
and listing it in run_stages(). A cron/launchd template for wiring this up
for real lives at scripts/templates/com.example.daily-maintenance.plist.template.

Usage:
  python3 scripts/daily_maintenance.py --dry-run     # print the digest only
  python3 scripts/daily_maintenance.py --no-ping     # write the digest, don't send
  python3 scripts/daily_maintenance.py               # write + send
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emit_daily_digest  # noqa: E402  (hub spool writer)
import hygiene_check  # noqa: E402  (imported, not subprocessed: it's a pure function)
import ticket_tracker  # noqa: E402  (shared _send_ping)

DIGEST_PATH = ".tmp/daily_maintenance/digest.md"
DRIFT_FILE = ".tmp/tracker_drift/ping.md"

PY = sys.executable

# ticket_tracker.py's own "not configured" exit code (TICKET_TRACKER_PROJECTS
# unset). Treated as skipped, not failed: most owners won't wire a tracker.
TRACKER_NOT_CONFIGURED_EXIT = 2


class Stage:
    """One stage's outcome. status: ok (has content) | empty (ran, nothing to
    say) | failed (errored). text is the section body; error is the failure."""

    def __init__(self, name):
        self.name = name
        self.status = "empty"
        self.text = ""
        self.error = ""


def _read(root, rel):
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def stage_hygiene(root):
    """Workspace hygiene findings, counted by severity. Content only when
    something needs attention (HIGH/MED); a clean scan is silent."""
    s = Stage("hygiene")
    try:
        # each finding: (severity, tag, group, message, path)
        findings = hygiene_check.run_checks(root)
        by_sev = {}
        for f in findings:
            by_sev[f[0]] = by_sev.get(f[0], 0) + 1
        needs_call = by_sev.get("HIGH", 0) + by_sev.get("MED", 0)
        if needs_call:
            s.status = "ok"
            counts = ", ".join(f"{n} {sev}" for sev, n in sorted(by_sev.items()))
            s.text = f"hygiene: {len(findings)} finding(s) ({counts})"
        else:
            s.text = "hygiene: clean"
    except Exception as e:  # noqa: BLE001  a stage never sinks the run
        s.status = "failed"
        s.error = "%s: %s" % (type(e).__name__, e)
    return s


def stage_tracker_drift(root):
    """Daily board-conformance sweep (tier-2 connector, off by default).
    Skipped (not failed) when NISSE_TRACKER_DRIFT isn't set or the board
    isn't configured; auto-fixes still happen inside when it does run."""
    s = Stage("tracker drift")
    if os.environ.get("NISSE_TRACKER_DRIFT") != "1":
        s.text = "tracker drift: NISSE_TRACKER_DRIFT not set, skipped"
        return s
    # Drop yesterday's payload so a clean day cannot read a stale ping.
    try:
        os.remove(os.path.join(root, DRIFT_FILE))
    except OSError:
        pass
    try:
        cmd = [PY, os.path.join(root, "scripts", "ticket_tracker.py"),
               "--root", root, "--sweep", "--no-ping"]
        p = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if p.returncode == TRACKER_NOT_CONFIGURED_EXIT:
            s.text = "tracker drift: TICKET_TRACKER_PROJECTS not set, skipped"
        elif p.returncode != 0:
            s.status = "failed"
            s.error = (p.stderr or p.stdout).strip()[:300] or "exit %d" % p.returncode
        else:
            txt = _read(root, DRIFT_FILE)
            if txt:
                s.status = "ok"
                s.text = txt
    except Exception as e:  # noqa: BLE001
        s.status = "failed"
        s.error = "%s: %s" % (type(e).__name__, e)
    return s


def stage_daily_digest(root):
    """Write this run's small JSON artifact into the hub's
    records/spool/nisse/, so a satellite daily run folds into the hub's one
    fleet digest. Local git signals only; failure here (e.g. hub path
    unwritable) is caught and reported, never sinks the other stages."""
    s = Stage("daily digest")
    try:
        path = emit_daily_digest.emit(root)
        s.status = "ok"
        s.text = f"daily digest: wrote {path}"
    except Exception as e:  # noqa: BLE001  a stage never sinks the run
        s.status = "failed"
        s.error = "%s: %s" % (type(e).__name__, e)
    return s


def run_stages(root):
    """Run every stage in order. Add your own stage function here to extend
    the example."""
    return [stage_hygiene(root), stage_tracker_drift(root), stage_daily_digest(root)]


def assemble(today, stages):
    """One digest. Stages with content lead; failures collected under Job
    health so a broken stage never hides behind silence."""
    by = {s.name: s for s in stages}
    parts = ["Daily maintenance (example) %s" % today.isoformat()]

    any_content = False
    for name in ("hygiene", "tracker drift", "daily digest"):
        s = by[name]
        if s.status == "ok" and s.text:
            parts += ["", "[ %s ]" % name, s.text]
            any_content = True

    failed = [s for s in stages if s.status == "failed"]
    if failed:
        parts += ["", "[ Job health ]"]
        parts += ["- %s: %s" % (s.name, s.error or "failed") for s in failed]
        any_content = True

    if not any_content:
        parts += ["", "all clear: nothing needs your attention today"]

    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--no-ping", action="store_true",
                    help="run every stage and write the digest, do not send")
    ap.add_argument("--dry-run", action="store_true",
                    help="run stages, print the digest, write/send nothing")
    args = ap.parse_args(argv)
    root = args.root
    today = date.today()

    stages = run_stages(root)
    digest = assemble(today, stages)

    if not args.dry_run:
        path = os.path.join(root, DIGEST_PATH)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(digest + "\n")

    attempted = not (args.dry_run or args.no_ping)
    sent = bool(ticket_tracker._send_ping(root, digest)) if attempted else False

    print(digest)
    print(json.dumps({"stages": {s.name: s.status for s in stages},
                      "ping_sent": sent, "dry_run": bool(args.dry_run)}))
    # A failed send is the invisible failure mode (no digest + a "healthy"
    # cron), so fail loudly if you wire this up for real.
    return 1 if (attempted and not sent) else 0


if __name__ == "__main__":
    sys.exit(main())
