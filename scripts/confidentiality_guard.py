#!/usr/bin/env python3
"""Confidentiality guard for CI (CHI-219).

Deterministic, read-only. Fails the build (exit 1) if a tracked file leaks an
owner absolute home path, if a shipped example/fixture file has lost its
"this is synthetic" marker, or if `.gitignore` stops covering the local-only
data and config that must never enter git. Green output and exit 0 when clean.

Reuses `hygiene_check.py`'s machinery (read_text) rather than re-deriving it.
Stdlib only; defensive (a broken check degrades to a finding, never a crash).

Scope: git-tracked files only (`git ls-files`), so gitignored local data and
`.git/` are never scanned. A short self-exclusion list keeps the guard from
tripping on the very files that must *discuss* the leak patterns — this script,
its test, and the plan/archive docs.

Run from the repo root:  python3 scripts/confidentiality_guard.py
Override the scanned root with $GUARD_ROOT or main(root=...).
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hygiene_check import read_text  # noqa: E402  (shared machinery, see docstring)

# ---- config -----------------------------------------------------------------

# The leak signal is an OWNER ABSOLUTE HOME PATH, not the bare username: the
# handle "chizhang" is the public GitHub/email identity (chizhangucb) and shows
# up in legit local tokens (e.g. chizhang-2), so we never auto-fail on it. We
# match only a home-directory prefix immediately followed by the username.
HOME_PATH_RE = re.compile(r"[/\\](?:Users|home)[/\\]chizhang(?![\w-])")

# Files that legitimately CARRY leak-shaped strings because they document the
# guard itself. Scanning them would fail the guard on its own commit. Matched
# against the repo-relative path (prefix match on the dir entries).
SELF_EXCLUDED_FILES = {
    "scripts/confidentiality_guard.py",
    "scripts/tests/test_confidentiality_guard.py",
}
SELF_EXCLUDED_DIRS = ("plans/", "archives/plans/")

# Example/fixture files that must keep a visible "synthetic" marker, so nobody
# ever mistakes them for real owner data. Path -> checked for any marker word.
SYNTHETIC_FIXTURES = (
    "wiki/raw/transcripts/2026-01-05_example_weekly_sync.md",
)
SYNTHETIC_MARKER_RE = re.compile(
    r"\b(example|synthetic|fixture|fake|sample|placeholder)\b", re.IGNORECASE)

# `.gitignore` must keep covering the local-only surfaces. Each entry is a
# substring that must appear on some (non-comment) .gitignore line.
REQUIRED_GITIGNORE = (
    ".env",
    "wiki/raw/transcripts/*",
    ".claude/settings.local.json",
    ".claude/state/",
    "records/.sessions_index.lock",
    ".tmp/",
)

# Binary-ish suffixes we never scan for path leaks (keeps the scan text-only).
SKIP_SCAN_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico",
                      ".zip", ".gz", ".woff", ".woff2", ".ttf")


def tracked_files(root):
    """Repo-relative paths of git-tracked files. Empty on any git failure
    (the caller reports that as a finding, never a crash)."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return None
        return [p for p in out.stdout.split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        return None


def _excluded(rel):
    return (rel in SELF_EXCLUDED_FILES
            or rel.startswith(SELF_EXCLUDED_DIRS))


def check_home_paths(root, rels, findings):
    for rel in rels:
        if _excluded(rel) or rel.endswith(SKIP_SCAN_SUFFIXES):
            continue
        text = read_text(os.path.join(root, rel))
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if HOME_PATH_RE.search(line):
                findings.append(
                    f"absolute owner home path leaked at {rel}:{i}: "
                    f"{line.strip()[:80]}")


def check_synthetic_markers(root, findings):
    for rel in SYNTHETIC_FIXTURES:
        path = os.path.join(root, rel)
        text = read_text(path)
        if text is None:
            # gitignore-excepted example may be absent in a fresh clone; only
            # flag a present-but-unmarked file, never a missing one.
            continue
        if not SYNTHETIC_MARKER_RE.search(text):
            findings.append(
                f"example fixture lost its synthetic marker "
                f"(needs one of example/synthetic/fixture/fake/sample): {rel}")


def check_gitignore(root, findings):
    text = read_text(os.path.join(root, ".gitignore"))
    if text is None:
        findings.append(".gitignore is missing; local data/config is unguarded")
        return
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    for needed in REQUIRED_GITIGNORE:
        if not any(needed in ln for ln in lines):
            findings.append(f".gitignore no longer covers '{needed}'")


def run_checks(root):
    findings = []
    rels = tracked_files(root)
    if rels is None:
        findings.append("git ls-files failed; not a git repo or git missing")
        return findings
    check_home_paths(root, rels, findings)
    check_synthetic_markers(root, findings)
    check_gitignore(root, findings)
    return findings


def main(root=None):
    root = os.path.abspath(root or os.environ.get("GUARD_ROOT") or os.getcwd())
    findings = run_checks(root)
    print(f"# Confidentiality guard, root: {root}")
    if not findings:
        print("clean: no leaked home paths, markers intact, .gitignore covers "
              "local data.")
        return 0
    print(f"# {len(findings)} finding(s):\n")
    for f in findings:
        print(f"[BLOCK] {f}")
    print("\nguard failed: fix the above before this can merge.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
