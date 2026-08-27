#!/usr/bin/env python3
"""Pre-PR staleness guard: refuse to land a branch behind origin/main.

Catches a stale branch before the PR opens instead of after it surfaces as a
surprise DIRTY conflict at merge time. Backs the repo's landing discipline
(governance/building.md): rebase onto current main + dry-run the merge before
landing; this is the unskippable version of that step.

Behavior:
  * fetch origin/main (skip with --no-fetch, for tests using a local ref)
  * even-or-ahead of the target -> exit 0 (merging main is a no-op, no conflict)
  * behind the target           -> exit 1, with a per-file conflict map from a
                                    `git merge --no-commit --no-ff` dry-run that
                                    is always aborted (CI-safe: never mutates the
                                    branch, never leaves a dirty tree)

Stdlib only, read-only against the repo except a merge dry-run it always aborts.

Usage:
    python3 scripts/landing_preflight.py [--repo PATH] [--target REF] [--no-fetch]

Exit: 0 up-to-date-and-clean; 1 behind or conflicting; 2 on a usage/env error
(e.g. an already-dirty tracked tree, which this guard refuses to touch).
"""
import argparse
import subprocess
import sys


def _git(repo, args, allow_fail=False):
    """Run git in `repo`; return trimmed stdout, or None when allow_fail and it
    exits non-zero. Raises RuntimeError on failure unless allow_fail."""
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        if allow_fail:
            return None
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def _rev_list_count(repo, rng):
    return int(_git(repo, ["rev-list", "--count", rng]) or "0")


def run_preflight(repo=".", target="origin/main", fetch=True):
    """Run the staleness preflight against `target`. Returns a dict:
    {target, behind, ahead, stale, conflicts, clean, verdict}. Pure w.r.t. the
    checked-out branch: any merge dry-run it starts is aborted before returning.
    """
    # Refuse to operate with uncommitted TRACKED changes: the dry-run + abort
    # below can only guarantee restoration from a clean index/worktree. Untracked
    # files (porcelain "??") are safe: merge --abort never touches them, and a
    # merge that would clobber one aborts on its own, so they do not block.
    porcelain = _git(repo, ["status", "--porcelain"]) or ""
    tracked_dirty = [
        ln for ln in porcelain.splitlines() if ln and not ln.startswith("??")
    ]
    if tracked_dirty:
        raise RuntimeError(
            "uncommitted tracked changes present; commit or stash before "
            "running the staleness guard:\n" + "\n".join(tracked_dirty)
        )

    if fetch:
        # Best-effort refresh; a failure is fatal only if the target then does
        # not resolve, below.
        _git(repo, ["fetch", "origin", "main"], allow_fail=True)

    resolved = _git(
        repo, ["rev-parse", "--verify", "--quiet", f"{target}^{{commit}}"],
        allow_fail=True,
    )
    if resolved is None:
        raise RuntimeError(
            f"target ref {target!r} not found (fetch failed or ref missing)"
        )

    behind = _rev_list_count(repo, f"HEAD..{target}")
    ahead = _rev_list_count(repo, f"{target}..HEAD")

    # Even-or-ahead: nothing on the target that HEAD lacks, so merging it changes
    # nothing and cannot conflict. Clean pass, no dry-run needed.
    if behind == 0:
        return {
            "target": target, "behind": behind, "ahead": ahead, "stale": False,
            "conflicts": [], "clean": True, "verdict": "pass",
        }

    # Behind: dry-run the merge purely to build the conflict map. The verdict is
    # already fail (behind == stale); the map only distinguishes "just rebase"
    # from "resolve these files first".
    head_before = _git(repo, ["rev-parse", "HEAD"])
    conflicts = []
    try:
        # --no-ff so a fast-forwardable-but-behind branch still exercises a real
        # merge; --no-commit so nothing is committed.
        _git(repo, ["merge", "--no-commit", "--no-ff", target], allow_fail=True)
        unmerged = _git(
            repo, ["diff", "--diff-filter=U", "--name-only"], allow_fail=True
        ) or ""
        conflicts = [ln.strip() for ln in unmerged.splitlines() if ln.strip()]
    finally:
        # Cleanup only. Never raise from a finally (it would mask a try-block
        # error): the HEAD check is done after this block, below. merge --abort
        # is a no-op-error when the merge was "Already up to date" (no
        # MERGE_HEAD); swallow that.
        _git(repo, ["merge", "--abort"], allow_fail=True)
    # Verify restoration after the finally.
    head_after = _git(repo, ["rev-parse", "HEAD"], allow_fail=True)
    if head_after != head_before:
        raise RuntimeError(
            f"staleness guard left HEAD moved ({head_before} -> "
            f"{head_after}); investigate manually"
        )

    return {
        "target": target, "behind": behind, "ahead": ahead, "stale": True,
        "conflicts": conflicts, "clean": not conflicts, "verdict": "fail",
    }


def render(r):
    lines = [
        f"staleness guard: HEAD vs {r['target']}",
        f"  behind: {r['behind']}   ahead: {r['ahead']}",
    ]
    if r["verdict"] == "pass":
        lines.append("  VERDICT: PASS (even-or-ahead of main).")
        return "\n".join(lines)
    if r["clean"]:
        lines.append(
            f"  behind main by {r['behind']} commit(s), no conflicts: "
            "rebase onto main before opening the PR."
        )
    else:
        lines.append(
            "  behind main AND conflicting. Resolve these files before landing:"
        )
        lines.extend(f"    - {f}" for f in r["conflicts"])
    lines.append(
        "  VERDICT: FAIL (branch is behind main). Rebase/sync onto current "
        "main, then re-run."
    )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Pre-PR staleness guard (behind-main + conflict map)."
    )
    ap.add_argument("--repo", default=".", help="repo path (default: cwd)")
    ap.add_argument(
        "--target", default="origin/main",
        help="landing target (default: origin/main)",
    )
    ap.add_argument(
        "--no-fetch", dest="fetch", action="store_false",
        help="do not fetch the target ref first",
    )
    args = ap.parse_args(argv)
    try:
        result = run_preflight(args.repo, args.target, args.fetch)
    except RuntimeError as err:
        print(f"staleness guard: {err}", file=sys.stderr)
        return 2
    print(render(result))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
