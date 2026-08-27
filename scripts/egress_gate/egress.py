#!/usr/bin/env python3
"""The egress gate shim (tier 3, dormant until wired; see README.md).

Usage: egress <verb> [args...]
       egress git push [args...]
       egress help

Every outbound action routes through here. The gate classifies the verb
(data/classification.json), scans the content against your confidentiality
markers (data/confidential_markers.json), verifies the remote pin for pushes,
and either executes, asks, or blocks. Fail-closed and fail-visible: an
unclassified verb asks (or denies unattended), and every non-execution prints
why and the fix.

Design floor (governance/gating.md):
- A marker hit hard-blocks. No posture, principal, or flag overrides it.
- The gate reads no who-initiated signal. Nothing in the environment lowers
  approval.
- Silence never approves. No TTY and no auto posture means deny, loudly.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSIFICATION = os.path.join(HERE, "data", "classification.json")
MARKERS = os.path.join(HERE, "data", "confidential_markers.json")


def die(msg, code=1):
    print(f"egress: {msg}", file=sys.stderr)
    return code


def load_json(path, what):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except ValueError as e:
        print(f"egress: {what} is unreadable JSON ({e}); fix it before any "
              f"send can fire: {path}", file=sys.stderr)
        sys.exit(2)


def load_markers():
    data = load_json(MARKERS, "confidential markers")
    if data is None:
        return []
    pats = []
    for entry in data.get("markers", []):
        try:
            pats.append(re.compile(entry, re.IGNORECASE))
        except re.error:
            print(f"egress: bad marker regex skipped: {entry!r}", file=sys.stderr)
    return pats


def scan(text, markers):
    """Marker patterns that hit in `text`. A hit hard-blocks upstream."""
    return [p.pattern for p in markers if p.search(text or "")]


def confirm(summary):
    """One explicit yes on a TTY; anything else is a no. Unattended (no TTY)
    always refuses: there is nobody to ask, and silence never approves."""
    if not sys.stdin.isatty():
        print("egress: approval needed but no interactive terminal; denied "
              "(fail-closed). Re-run from a terminal to approve.",
              file=sys.stderr)
        return False
    print(summary)
    try:
        answer = input("approve? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def run(argv):
    try:
        return subprocess.run(argv).returncode
    except OSError as e:
        return die(f"could not execute {argv[0]}: {e}")


# ---------------------------------------------------------------------------
# git push: pin check + outgoing-diff scan
# ---------------------------------------------------------------------------

def _git(args, cwd=None):
    try:
        out = subprocess.run(["git"] + args, cwd=cwd, capture_output=True,
                             text=True, timeout=30)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def outgoing_diff():
    """The full text a push would publish: diff + log messages upstream..HEAD.
    None when no upstream is set (then everything is 'outgoing' and we scan
    the branch tip's diff against the remote default instead of guessing)."""
    upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    rng = f"{upstream}..HEAD" if upstream else "HEAD"
    diff = _git(["diff", rng]) if upstream else _git(["show", "HEAD"])
    log = _git(["log", rng, "--pretty=%B"]) if upstream else ""
    return (diff or "") + "\n" + (log or "")


def gate_git_push(args, config, markers):
    remote_url = _git(["remote", "get-url", "origin"]) or "(no origin)"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]) or "?"
    pins = config.get("push_pins", {})
    repo_root = _git(["rev-parse", "--show-toplevel"]) or os.getcwd()
    pin = pins.get(os.path.basename(repo_root), pins.get("*", ""))

    hits = scan(outgoing_diff(), markers)
    if hits:
        return die("BLOCKED: the outgoing diff matches confidentiality "
                   f"marker(s) {hits}. Nothing pushed. Remove or rewrite the "
                   "matching content (or fix a stale marker in "
                   "data/confidential_markers.json), then retry.", 3)

    pinned_ok = bool(pin) and pin in remote_url
    posture = config.get("verbs", {}).get("git push", {}).get(
        "posture", "ask")
    summary = (f"git push\n  remote: {remote_url}\n  branch: {branch}\n"
               f"  pin: {pin or '(none configured)'}\n  scan: clean")

    if posture == "conditioned-auto" and pinned_ok:
        print(f"egress: push auto-approved (scan clean, remote matches pin "
              f"'{pin}', branch {branch})")
        return run(["git", "push"] + args)
    if not pinned_ok and pin:
        print(f"egress: remote does not match the pin '{pin}'; asking instead "
              "of auto.", file=sys.stderr)
    if confirm(summary):
        return run(["git", "push"] + args)
    return die("push not approved; nothing sent.", 4)


# ---------------------------------------------------------------------------
# generic verbs
# ---------------------------------------------------------------------------

def gate_verb(verb, args, config, markers):
    row = config.get("verbs", {}).get(verb)
    if row is None:
        # fail-closed: unclassified action
        summary = (f"UNCLASSIFIED command: {verb} {' '.join(args)}\n"
                   "Add a row to data/classification.json to set its posture.")
        if confirm(summary):
            return run(row_exec(None, verb, args))
        return die(f"'{verb}' is unclassified and was not approved. Classify "
                   "it in data/classification.json.", 5)

    hits = scan(" ".join(args), markers)
    if hits:
        return die(f"BLOCKED: arguments match confidentiality marker(s) "
                   f"{hits}. Nothing sent.", 3)

    posture = row.get("posture", "ask")
    summary = f"{verb} ({row.get('class', 'send')}): {verb} {' '.join(args)}"
    if posture == "auto":
        return run(row_exec(row, verb, args))
    # ask / confirm-always both prompt; the difference (standing grants can
    # pre-satisfy 'ask') needs the instance-layer grant store, not shipped.
    if confirm(summary):
        return run(row_exec(row, verb, args))
    return die(f"'{verb}' not approved; nothing sent.", 4)


def row_exec(row, verb, args):
    if row and row.get("exec"):
        return row["exec"] + args
    return verb.split() + args


def cmd_help(config):
    print("egress: gated outbound commands (data/classification.json)\n")
    verbs = (config or {}).get("verbs", {})
    if not verbs:
        print("  (no verbs classified yet; see scripts/egress_gate/README.md "
              "to wire the gate)")
        return 0
    for verb, row in sorted(verbs.items()):
        print(f"  egress {verb:<24} {row.get('class', '?'):<8} "
              f"{row.get('posture', 'ask')}")
    return 0


def main(argv):
    if len(argv) < 1 or argv[0] in ("help", "--help", "-h"):
        return cmd_help(load_json(CLASSIFICATION, "classification"))

    config = load_json(CLASSIFICATION, "classification")
    if config is None:
        return die("not wired yet: data/classification.json does not exist. "
                   "The gate ships dormant; see scripts/egress_gate/README.md "
                   "for the wiring steps. Nothing was sent.", 2)
    markers = load_markers()
    if not os.path.exists(MARKERS):
        print("egress: warning: data/confidential_markers.json missing; the "
              "content scan is running EMPTY. Create it from the example "
              "file.", file=sys.stderr)

    if argv[0] == "git" and len(argv) >= 2 and argv[1] == "push":
        return gate_git_push(argv[2:], config, markers)
    return gate_verb(argv[0], argv[1:], config, markers)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
