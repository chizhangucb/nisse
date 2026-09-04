#!/usr/bin/env python3
"""Install the pre-push secret guard into public-remote repos (ADR-0001).

For each candidate repo: read its origin remote, ask GitHub for the repo's
visibility, and install the pre-push hook into that repo's own
`.git/hooks/pre-push` only when the remote is PUBLIC or INTERNAL (both visible
beyond the owner). A private or remote-less repo gets nothing; a repo that was
public and went private has our managed hook removed, so the end state always
matches visibility. Re-run after a clone or a visibility flip.

The hook we install carries a `managed-by: nisse-push-guard` marker line, so we
only ever overwrite or remove hooks we own. An unrelated hand-written pre-push
hook is left untouched and reported.

Usage:
  install_push_guard.py [--dry-run] [REPO_PATH ...]

With no REPO_PATH, the repo this script lives in is used. Pass paths to install
the guard into other clones on the same machine.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK_SOURCE = HERE / "pre-push-secret-scan"
MANAGED_MARKER = "managed-by: nisse-push-guard"

# With no path argument, guard the repo this script ships in.
DEFAULT_REPOS = [HERE.parent.parent]


def _run(cmd, cwd=None):
    """Run a command, returning (exit_code, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    except (FileNotFoundError, NotADirectoryError):
        return 127, "", "cwd does not exist"
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def origin_url(repo: Path):
    """The origin remote URL, or None if the path is not a git repo / has no origin.

    Covers a missing path (repo not cloned yet), a plain dir, and worktrees whose
    .git is a file rather than a directory.
    """
    if not repo.is_dir():
        return None
    code, _, _ = _run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo)
    if code != 0:
        return None
    code, out, _ = _run(["git", "remote", "get-url", "origin"], cwd=repo)
    return out if code == 0 and out else None


def github_slug(url: str):
    """owner/repo from an https or ssh GitHub remote URL, else None."""
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def visibility(slug: str):
    """PUBLIC / PRIVATE / INTERNAL for a GitHub slug via gh, or None on failure."""
    code, out, _ = _run(["gh", "repo", "view", slug, "--json", "visibility"])
    if code != 0 or not out:
        return None
    try:
        return json.loads(out).get("visibility")
    except json.JSONDecodeError:
        return None


def hook_path(repo: Path):
    """The repo's physical .git/hooks/pre-push.

    Resolves via --git-common-dir (the .git directory, shared across worktrees)
    and joins hooks/pre-push, so the guard lands in the repo's own hooks
    directory. Returns None when repo is not a git work tree.
    """
    if not repo.is_dir():
        return None
    code, out, _ = _run(["git", "rev-parse", "--git-common-dir"], cwd=repo)
    if code != 0 or not out:
        return None
    gitdir = Path(out)
    if not gitdir.is_absolute():
        gitdir = repo / gitdir
    return gitdir / "hooks" / "pre-push"


def is_ours(path: Path):
    return path.exists() and MANAGED_MARKER in path.read_text(errors="ignore")


def install(repo: Path, dry_run=False):
    """Install the hook into repo. Returns a human-readable status string."""
    dest = hook_path(repo)
    if dest is None:
        # A work tree whose .git points nowhere resolvable: report, touch nothing.
        return f"SKIP  (cannot resolve .git/hooks): {repo}"
    if dest.exists() and not is_ours(dest):
        return f"SKIP  (foreign pre-push hook present, left untouched): {dest}"
    # A re-run must be a true no-op: only write when the contents actually differ,
    # so an unchanged install rewrites nothing.
    current = dest.read_text() if dest.exists() else None
    wanted = HOOK_SOURCE.read_text()
    if current == wanted and os.access(dest, os.X_OK):
        return f"already current -> {dest}"
    if dry_run:
        return f"WOULD INSTALL -> {dest}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HOOK_SOURCE, dest)
    dest.chmod(0o755)
    return f"INSTALLED -> {dest}"


def remove_if_ours(repo: Path, dry_run=False):
    """Remove our managed hook if present. Returns a status string or None."""
    dest = hook_path(repo)
    if dest is not None and is_ours(dest):
        if dry_run:
            return f"WOULD REMOVE (repo not public) -> {dest}"
        dest.unlink()
        return f"REMOVED (repo not public) -> {dest}"
    return None


def process(repo: Path, dry_run=False):
    """Decide and act for one repo. Returns (repo, verdict, detail)."""
    url = origin_url(repo)
    if url is None:
        return (repo, "skip", "not a git repo with an origin remote")
    slug = github_slug(url)
    if slug is None:
        return (repo, "skip", f"origin is not a GitHub remote ({url})")
    vis = visibility(slug)
    if vis is None:
        return (repo, "skip", f"could not read visibility for {slug} (gh error)")
    # PUBLIC and INTERNAL are both visible beyond the owner, so both get the guard.
    if vis in ("PUBLIC", "INTERNAL"):
        return (repo, vis.lower(), install(repo, dry_run))
    detail = remove_if_ours(repo, dry_run) or "no hook needed"
    return (repo, vis.lower(), detail)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repos", nargs="*", help="repo paths (default: this repo)")
    ap.add_argument("--dry-run", action="store_true", help="report actions without touching hooks")
    args = ap.parse_args(argv)

    if not HOOK_SOURCE.exists():
        print(f"error: canonical hook missing: {HOOK_SOURCE}", file=sys.stderr)
        return 2

    repos = [Path(os.path.expanduser(r)).resolve() for r in args.repos] or DEFAULT_REPOS
    results = [process(r, args.dry_run) for r in repos]

    for repo, verdict, detail in results:
        print(f"[{verdict:8}] {repo}\n           {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
