#!/usr/bin/env bash
# managed-by: nisse-git-guard
#
# Destructive-git guard (ADR-0001). A PreToolUse hook on the Bash tool that
# refuses four irreversible git commands and passes everything else:
#   1. hard reset          -- discards uncommitted work
#   2. forced clean        -- deletes untracked files
#   3. branch force-delete -- but only of a branch not yet in origin/main
#                             (a stale origin/main is refetched, see rule 3)
#   4. force-push to main  -- rewrites shared history
# Wire it machine-wide from ~/.claude/settings.json (PreToolUse, matcher "Bash")
# pointing at this file. Reads the tool call as JSON on stdin; exit 2 blocks
# with a reason, exit 0 allows. Adapted from Matt Pocock's git-guardrails hook;
# the matching is ours.
#
# Two guard-wide choices: matching runs against the command with quoted "...",
# '...' and backtick `...` text removed (so a phrase inside an echo, commit
# message, or markdown code span is not read as the command), and patterns
# avoid \b (unreliable in BSD/macOS grep) and stop at && | ; so a flag in one
# chained command cannot pair with a target in another. This is an accident
# net, not a security boundary.

set -euo pipefail
set -f  # we word-split command tokens on purpose below; no filename globbing

input=$(cat)

# The command, from the tool-call JSON. jq if present, else a sed fallback so a
# missing jq never lets a command through unchecked.
if command -v jq >/dev/null 2>&1; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
else
  cmd=$(printf '%s' "$input" \
    | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\(.*\)".*/\1/p')
fi
[ -z "$cmd" ] && exit 0

# What we match on: escaped quotes then quoted and backtick-wrapped regions
# stripped out (a trigger phrase in a markdown code span of a gh body).
scan=$(printf '%s' "$cmd" \
  | sed -e 's/\\"//g' -e 's/"[^"]*"//g' -e "s/'[^']*'//g" -e 's/`[^`]*`//g')

block() {
  echo "git-guard: blocked: $1" >&2
  exit 2
}

# Run "$@" but give up after $1 wall-clock seconds, so a hung or prompting remote
# cannot stall the tool call this hook blocks on. The child runs in its own
# process group (set -m) and the timeout kills the group, not just the leader:
# git delegates to ssh or git-remote-https, and killing only git would leave the
# child that is actually hanging behind. Returns non-zero on timeout or failure.
run_bounded() {
  local limit="$1" pid deadline
  shift
  deadline=$(( $(date +%s) + limit ))
  set -m
  "$@" >/dev/null 2>&1 &
  pid=$!
  set +m
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      kill -9 -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || :
      wait "$pid" 2>/dev/null || :
      return 1
    fi
    sleep 0.1
  done
  wait "$pid"
}

# Refresh refs/remotes/origin/main, at most once per hook run. A branch is
# usually deleted right after its PR merged, when the local remote-tracking ref
# is one commit behind the squash that merged it; without this the guard would
# refuse a genuinely merged branch and the caller would have to know to fetch
# first. Best effort: a failed or timed-out fetch just leaves the stale ref, and
# the merge check below still has to pass.
_fetched_origin_main=0
refresh_origin_main() {
  # Non-zero here means "no fresher ref than the caller already saw", whether
  # because the fetch failed or because this run already did it. Either way the
  # caller must fall back to the merge check, so one return code covers both.
  [ "$_fetched_origin_main" = 1 ] && return 1
  _fetched_origin_main=1
  GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=true SSH_ASKPASS=true \
    run_bounded 10 git fetch --quiet --no-tags origin main
}

# Return 0 if branch $1 is fully contained in origin/main as it stands right now
# (true/ff merge = tip is an ancestor; rebase merge = git cherry finds a
# patch-id twin for every commit; squash merge = the branch's combined diff has
# a patch-id twin among recent main commits). Fail-safe: any error or missing
# ref returns non-zero (caller blocks).
branch_contained_in_main() {
  local b="$1" mb want cherry
  git merge-base --is-ancestor "$b" origin/main 2>/dev/null && return 0
  mb=$(git merge-base origin/main "$b" 2>/dev/null) || return 1
  cherry=$(git cherry origin/main "$b" 2>/dev/null) || return 1
  printf '%s' "$cherry" | grep -q '^+' || return 0
  want=$(git diff "$mb" "$b" 2>/dev/null | git patch-id 2>/dev/null | cut -d' ' -f1)
  [ -n "$want" ] || return 1
  git log -p --no-merges -n 200 "$mb..origin/main" 2>/dev/null \
    | git patch-id 2>/dev/null | grep -q "^$want" && return 0
  return 1
}

# Return 0 if branch $1 is fully contained in origin/main. On a miss, refresh
# origin/main once and re-check, so a stale remote-tracking ref never reads as
# unmerged work.
branch_merged_into_main() {
  branch_contained_in_main "$1" && return 0
  refresh_origin_main || return 1
  branch_contained_in_main "$1"
}

# 1) git reset --hard
if printf '%s' "$scan" \
    | grep -qE 'git[[:space:]]+reset[[:space:]][^&|;]*--hard([^[:alnum:]]|$)'; then
  block "git reset --hard destroys uncommitted work"
fi

# 2) git clean with a force flag (-f, -fd, --force, ...) at a token start, so a
# pathspec like "build-f" does not trip it.
if printf '%s' "$scan" \
    | grep -qE 'git[[:space:]]+clean([[:space:]][^&|;]*)?[[:space:]](-[[:alnum:]]*f|--force)'; then
  block "git clean -f deletes untracked files"
fi

# 3) git branch force-delete (-D, or --delete --force). Allowed once every named
# branch is fully in origin/main (post-merge cleanup); blocked otherwise. Each
# "git branch ..." segment is checked, so a chained "a && b" cannot slip an
# unmerged delete past the first. The -D must be at a token start ("feature-D" is
# a name, not the flag). Fail-safe: unknown branch or no origin/main blocks.
branch_segs=$(printf '%s' "$scan" | grep -oE 'git[[:space:]]+branch[^&|;]*' || true)
if [ -n "$branch_segs" ]; then
  while IFS= read -r seg; do
    [ -n "$seg" ] || continue
    printf '%s' "$seg" \
      | grep -qE '([[:space:]]|^)-[[:alnum:]]*D([^[:alnum:]]|$)|--delete[^&|;]*--force|--force[^&|;]*--delete' \
      || continue  # not a force-delete (create/list/rename) -> skip
    branches=""
    for tok in $seg; do
      # skip the git/branch words, flags, and shell redirections (2>&1, >log)
      case "$tok" in git|branch) continue ;; -*) continue ;; *'>'*|*'<'*) continue ;; esac
      branches="$branches $tok"
    done
    [ -n "${branches// /}" ] \
      || block "git branch -D: no branch named to verify; refusing"
    git rev-parse --verify --quiet origin/main >/dev/null 2>&1 \
      || refresh_origin_main || :
    git rev-parse --verify --quiet origin/main >/dev/null 2>&1 \
      || block "git branch -D: cannot reach origin/main to verify merge; refusing"
    for b in $branches; do
      git rev-parse --verify --quiet "refs/heads/$b" >/dev/null 2>&1 \
        || block "git branch -D: unknown branch '$b'; refusing"
      branch_merged_into_main "$b" \
        || block "git branch -D: '$b' has commits not in origin/main; refusing"
    done
  done <<EOF
$branch_segs
EOF
fi

# 4) force-push that could hit main. Within the "git push ..." segment, a force
# flag (--force, --force-with-lease, -f, -fu) or a "+main" refspec makes it
# force-active; that is refused when it targets main or names no explicit branch
# (a bare force-push pushes the current branch, which may be main). A force-push
# naming a feature branch passes.
push_seg=$(printf '%s' "$scan" | grep -oE 'git[[:space:]]+push[^&|;]*' || true)
if [ -n "$push_seg" ]; then
  targets_main=$(printf '%s' "$push_seg" \
    | grep -qE '([^[:alnum:]/]|^)main([^[:alnum:]-]|$)' && echo yes || true)
  force_flag=$(printf '%s' "$push_seg" \
    | grep -qE '(--force|([[:space:]]|^)-[[:alnum:]]*f[[:alnum:]]*([^[:alnum:]]|$))' && echo yes || true)
  plus_main=$(printf '%s' "$push_seg" \
    | grep -qE '[[:space:]]\+[^[:space:]]*main([^[:alnum:]-]|$)' && echo yes || true)

  if [ -n "$force_flag" ] || [ -n "$plus_main" ]; then
    if [ -n "$targets_main" ] || [ -n "$plus_main" ]; then
      block "force-push to main rewrites shared history"
    fi
    # Allow only when a concrete non-main, non-HEAD destination is named. The
    # first positional after push is the remote; the rest are refspecs.
    safe_refspec=""
    n=0
    for tok in $push_seg; do
      # skip the git/push words, flags, and shell redirections (2>&1, >log): a
      # redirection token must not be mistaken for the destination branch.
      case "$tok" in git|push) continue ;; -*) continue ;; *'>'*|*'<'*) continue ;; esac
      n=$((n + 1))
      [ "$n" -eq 1 ] && continue
      dest=${tok#+}
      case "$dest" in *:*) dest=${dest##*:} ;; esac
      if [ -n "$dest" ] && [ "$dest" != "main" ] && [ "$dest" != "HEAD" ]; then
        safe_refspec=yes
      fi
    done
    [ -z "$safe_refspec" ] \
      && block "force-push without a named branch may hit main; pass origin <branch>"
  fi
fi

exit 0
