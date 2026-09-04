# Git guards

Two local git guards, both fail-closed, no daemon and no approval step.

1. **Push guard** -- a per-repo pre-push hook, installed only into repos whose
   origin is a public (or internal) GitHub remote. A push carrying a secret or a
   `CONFIDENTIAL` marker file is rejected.
2. **Destructive-git guard** -- a machine-wide PreToolUse hook that refuses four
   irreversible git commands before an agent runs them.

## Files

- `pre-push-secret-scan` -- the git pre-push hook, installed into a repo's own
  `.git/hooks/pre-push`. Over the pushed commit range it (1) runs `gitleaks` and
  rejects any secret, and (2) rejects any file named `CONFIDENTIAL` in the range,
  the marker `docs/confidentiality.md` puts on a folder that never leaves the
  machine. Both checks always enforce -- the hook lives only in repos others can
  read, so there is no per-push visibility probe and no network call on push.
  Fails closed: if `gitleaks` is not on PATH, the push is refused.
- `install_push_guard.py` -- reads each candidate repo's origin visibility via
  `gh` and installs the hook into that repo's own `.git/hooks/pre-push` when the
  remote is PUBLIC or INTERNAL, removing our managed copy when it is PRIVATE. Only
  ever touches hooks carrying the `managed-by: nisse-push-guard` marker;
  idempotent; a hand-written foreign hook is left untouched and reported. Re-run
  after cloning a repo or when a repo's visibility flips (a public->private flip
  removes the hook).
- `block-dangerous-git.sh` -- the destructive-git PreToolUse hook. Reads the Bash
  tool call as JSON on stdin and exits 2 (blocking) for a hard reset, a forced
  clean, a branch force-delete of a branch **not** yet in `origin/main`, or a
  force-push that could hit `main`. Plain push and every other command pass.
  Notes:
  - A force-push must name a concrete feature branch (`git push --force origin
    <branch>`); a bare or branchless force-push is refused, since it pushes the
    current branch and the command string cannot tell whether that is main.
  - A branch force-delete is allowed once the branch is fully contained in
    `origin/main` (true, rebase, or squash merge, detected via ancestry, `git
    cherry`, and a combined patch-id match), so post-merge cleanup works; it stays
    blocked while the branch has commits absent from `origin/main`. A stale
    `origin/main` is not yours to remember: on a miss the guard fetches `origin
    main` once (bounded to 10s, no credential prompts) and re-checks, so deleting
    a branch straight after its PR squash-merged works without a pull first.
    Fail-safe: if merge status cannot be proven (not a repo, no `origin/main`,
    unknown branch, fetch failed or timed out), it blocks.
  - Matching ignores quoted `"..."`/`'...'` text and shell redirections
    (`2>&1`, `>log`), so a trigger phrase inside an echo, comment, or commit/PR
    body does not false-positive and a redirection is not mistaken for a branch.

  Wire it machine-wide from `~/.claude/settings.json` (`PreToolUse`, matcher
  `Bash`), pointing at this file (directly, or via a symlink under
  `~/.claude/hooks/`) so there is one tracked source of truth. Keep the primary
  checkout on `main` (sessions use their own worktrees) so the symlink resolves
  to the merged version.

## Install / refresh

    brew install gitleaks                                  # one-time; the hook needs it
    python3 scripts/guards/install_push_guard.py            # install into this repo
    python3 scripts/guards/install_push_guard.py --dry-run  # show, do nothing
    python3 scripts/guards/install_push_guard.py <path> ... # target other repos

With no path, this repo is used. Re-run after cloning (the hook is per-repo, not
inherited) or when a repo's visibility flips: a public->private flip removes the
hook, a private->public flip installs it.

## Bypass

Push guard: git's own escape hatch, `git push --no-verify`, skips all pre-push
hooks. For a single false positive prefer gitleaks' own `.gitleaksignore` or an
inline `gitleaks:allow` comment.

Destructive-git guard: remove or edit the `PreToolUse` block in
`~/.claude/settings.json`, or run the intended command outside an agent session.

## Tests

    python3 -m pytest scripts/tests/test_push_guard.py scripts/tests/test_dangerous_git.py
