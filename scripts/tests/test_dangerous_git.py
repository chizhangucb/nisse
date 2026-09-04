"""Tests for the destructive-git guard (ADR-0001).

Seam: the hook (scripts/guards/block-dangerous-git.sh) reads a Bash tool call as
JSON on stdin and exits 2 with a one-line reason for a blocked command, or 0 for
an allowed one. The test drives that real entry point -- it feeds tool-call JSON
and asserts on exit code and stderr, never on internals.

Rule 3 (branch force-delete) consults real git state, so its tests run the hook
with cwd set to a throwaway fixture repo built per case.
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "guards" / "block-dangerous-git.sh"


def run_hook(command, cwd=None, env=None):
    """Invoke the hook as Claude Code would, with the tool call on stdin."""
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [str(HOOK)], input=payload, capture_output=True, text=True, cwd=cwd,
        env={**os.environ, **env} if env else None,
    )


class Blocked(unittest.TestCase):
    def assert_blocked(self, command, reason_fragment):
        r = run_hook(command)
        self.assertEqual(r.returncode, 2, f"expected block for: {command}\n{r.stderr}")
        self.assertIn("git-guard: blocked", r.stderr)
        self.assertIn(reason_fragment, r.stderr)

    def test_reset_hard(self):
        self.assert_blocked("git reset --hard", "uncommitted work")

    def test_reset_hard_with_ref(self):
        self.assert_blocked("git reset --hard HEAD~3", "uncommitted work")

    def test_clean_force(self):
        self.assert_blocked("git clean -f", "untracked files")

    def test_clean_force_dir(self):
        self.assert_blocked("git clean -fd", "untracked files")

    def test_clean_force_long(self):
        self.assert_blocked("git clean --force", "untracked files")

    def test_force_push_main(self):
        self.assert_blocked("git push --force origin main", "shared history")

    def test_force_push_main_short_flag(self):
        self.assert_blocked("git push -f origin main", "shared history")

    def test_force_with_lease_main(self):
        self.assert_blocked("git push --force-with-lease origin main", "shared history")

    def test_force_push_main_flag_after_refspec(self):
        self.assert_blocked("git push origin main --force", "shared history")

    def test_force_push_plus_refspec_main(self):
        # A "+" refspec force-updates main with no force flag.
        self.assert_blocked("git push origin +main", "shared history")

    def test_force_push_plus_head_main(self):
        self.assert_blocked("git push origin +HEAD:main", "shared history")

    def test_force_push_combined_short_flags_main(self):
        self.assert_blocked("git push -fu origin main", "shared history")

    def test_bare_force_push_blocked(self):
        # No branch named: pushes the current branch, which may be main.
        self.assert_blocked("git push --force", "may hit main")

    def test_bare_force_with_lease_blocked(self):
        self.assert_blocked("git push --force-with-lease", "may hit main")

    def test_force_push_remote_only_blocked(self):
        # A remote but no refspec still pushes the current branch.
        self.assert_blocked("git push -f origin", "may hit main")

    def test_force_push_head_only_blocked(self):
        # HEAD resolves to the current branch, so it is as ambiguous as bare.
        self.assert_blocked("git push --force origin HEAD", "may hit main")

    def test_force_push_remote_only_with_redirect_blocked(self):
        # A shell redirection must not be mistaken for the destination branch,
        # which would re-open the branchless force-push.
        self.assert_blocked("git push --force origin 2>&1", "may hit main")

    def test_force_push_remote_only_with_devnull_redirect_blocked(self):
        self.assert_blocked("git push --force origin 2>/dev/null", "may hit main")

    def test_force_push_main_with_redirect_blocked(self):
        self.assert_blocked("git push --force origin main 2>&1", "shared history")

    def test_dangerous_in_chained_command(self):
        # A destructive command hidden after && is still caught.
        self.assert_blocked("cd /tmp && git reset --hard", "uncommitted work")


class Allowed(unittest.TestCase):
    def assert_allowed(self, command):
        r = run_hook(command)
        self.assertEqual(r.returncode, 0, f"expected allow for: {command}\n{r.stderr}")

    def test_plain_push(self):
        self.assert_allowed("git push")

    def test_plain_push_origin_main(self):
        # Plain (non-force) push to main is fine; only force-push is blocked.
        self.assert_allowed("git push origin main")

    def test_force_push_feature_branch(self):
        self.assert_allowed("git push --force origin feature-x")

    def test_force_with_lease_feature_branch(self):
        self.assert_allowed("git push --force-with-lease origin my-branch")

    def test_force_push_head_to_feature_dest(self):
        # An explicit non-main destination is safe even when the source is HEAD.
        self.assert_allowed("git push --force origin HEAD:topic")

    def test_force_push_plus_feature_branch(self):
        # A "+" force-push to a feature branch (not main) passes.
        self.assert_allowed("git push origin +feature-x")

    def test_force_push_feature_branch_with_redirect(self):
        # A trailing redirection does not change the verdict for a named branch.
        self.assert_allowed("git push --force origin feature-x 2>&1")

    def test_reset_soft(self):
        self.assert_allowed("git reset --soft HEAD~1")

    def test_reset_default(self):
        self.assert_allowed("git reset HEAD~1")

    def test_clean_dry_run(self):
        self.assert_allowed("git clean -n")

    def test_branch_safe_delete(self):
        self.assert_allowed("git branch -d merged-branch")

    def test_branch_name_trailing_capital_d(self):
        # A branch name ending in -D must not read as the -D force flag.
        self.assert_allowed("git branch feature-D")

    def test_branch_name_with_capital_d(self):
        self.assert_allowed("git branch my-Deploy")

    def test_branch_list(self):
        self.assert_allowed("git branch")

    def test_clean_dry_run_with_pathspec(self):
        # A pathspec ending in -f under a dry run must not read as the force flag.
        self.assert_allowed("git clean -n build-f")

    def test_unrelated_command(self):
        self.assert_allowed("ls -la && echo done")

    def test_git_status(self):
        self.assert_allowed("git status")

    def test_maintenance_branch_not_main(self):
        # A branch whose name merely contains "main" must not trip the guard.
        self.assert_allowed("git push --force origin maintenance")

    def test_empty_command(self):
        self.assert_allowed("")


class QuotedText(unittest.TestCase):
    """A trigger phrase inside a quoted literal (echo, comment, commit/PR body)
    must not be read as the command itself."""

    def assert_allowed(self, command):
        r = run_hook(command)
        self.assertEqual(r.returncode, 0, f"expected allow for: {command}\n{r.stderr}")

    def assert_blocked(self, command, reason_fragment):
        r = run_hook(command)
        self.assertEqual(r.returncode, 2, f"expected block for: {command}\n{r.stderr}")
        self.assertIn(reason_fragment, r.stderr)

    def test_echo_double_quoted_phrase(self):
        self.assert_allowed('echo "do not run git reset --hard here"')

    def test_echo_single_quoted_phrase(self):
        self.assert_allowed("echo 'git clean -fd is dangerous'")

    def test_commit_message_quoting_phrase(self):
        self.assert_allowed('git commit -m "explain git push --force origin main"')

    def test_branch_delete_phrase_in_string(self):
        self.assert_allowed('echo "cleanup uses git branch -D <name>"')

    def test_gh_issue_body_quoting_phrases(self):
        self.assert_allowed(
            'gh issue create --title x --body "the guard blocks git reset --hard"')

    def test_real_command_after_quoted_echo_still_blocked(self):
        # Only the quoted part is exempt; a real command outside quotes is caught.
        self.assert_blocked('echo "safe note" && git reset --hard', "uncommitted work")

    def test_escaped_double_quotes_in_echo(self):
        # An escaped quote inside a double-quoted string must not mis-pair and
        # re-expose the phrase.
        self.assert_allowed('echo "he said \\"run git reset --hard\\" now"')

    def test_escaped_double_quotes_in_commit_message(self):
        self.assert_allowed('git commit -m "fix the \\"git reset --hard\\" guard"')


class BacktickText(unittest.TestCase):
    """A trigger phrase inside a backtick-wrapped span (markdown code span in a
    gh PR/issue body, or a comment) must not be read as the command itself
   . Same family as QuotedText."""

    def assert_allowed(self, command):
        r = run_hook(command)
        self.assertEqual(r.returncode, 0, f"expected allow for: {command}\n{r.stderr}")

    def assert_blocked(self, command, reason_fragment):
        r = run_hook(command)
        self.assertEqual(r.returncode, 2, f"expected block for: {command}\n{r.stderr}")
        self.assertIn(reason_fragment, r.stderr)

    def test_gh_body_backtick_reset_hard(self):
        self.assert_allowed(
            'gh issue create --body-file - <<EOF\nthe guard blocks `git reset --hard`\nEOF')

    def test_gh_body_backtick_force_push(self):
        self.assert_allowed("gh pr create --title x --body 'run `git push --force` never'")

    def test_backtick_clean_force(self):
        self.assert_allowed("echo note about `git clean -fd` in a code span")

    def test_backtick_branch_delete(self):
        self.assert_allowed("echo cleanup uses `git branch -D <name>`")

    def test_real_command_outside_backticks_still_blocked(self):
        # Only the backtick span is exempt; a real command outside it is caught.
        self.assert_blocked("echo `a note` && git reset --hard", "uncommitted work")

    def test_real_force_push_outside_backticks_still_blocked(self):
        self.assert_blocked(
            "echo `see docs` && git push --force origin main", "shared history")


def _git(repo, *args, **kw):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, **kw
    ).stdout.strip()


class Rule3BranchDelete(unittest.TestCase):
    """Rule 3 consults real git state: a force-delete is allowed only when the
    branch is fully contained in origin/main. Each test builds a throwaway
    repo with a bare 'origin' so origin/main resolves."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "work")
        self.origin = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", self.origin], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        _git(self.repo, "config", "user.email", "t@t.co")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "remote", "add", "origin", self.origin)
        self._commit("base.md", "base\n", "base")
        self._push_main()

    def _commit(self, name, content, msg):
        p = Path(self.repo) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _git(self.repo, "add", name)
        _git(self.repo, "commit", "-qm", msg)
        return _git(self.repo, "rev-parse", "HEAD")

    def _push_main(self):
        _git(self.repo, "push", "-q", "origin", "main")
        _git(self.repo, "fetch", "-q", "origin")

    def _delete(self, branch):
        return run_hook(f"git branch -D {branch}", cwd=self.repo)

    def _squash_on_remote(self, files):
        """Land a commit on origin/main from a separate clone, so self.repo's
        refs/remotes/origin/main is left behind the way it is after a squash
        merge on the host."""
        other = os.path.join(self.tmp, f"other{time.monotonic_ns()}")
        subprocess.run(["git", "clone", "-q", self.origin, other], check=True)
        _git(other, "config", "user.email", "t@t.co")
        _git(other, "config", "user.name", "t")
        # The bare repo's HEAD follows init.defaultBranch, which is master on a
        # stock runner and main here, so the clone can land on an unborn branch.
        # Pin it to the ref this fixture actually pushes.
        _git(other, "checkout", "-q", "-B", "main", "origin/main")
        for name, content in files.items():
            (Path(other) / name).write_text(content)
            _git(other, "add", name)
        _git(other, "commit", "-qm", "squash on the remote")
        _git(other, "push", "-q", "origin", "main")

    def test_unmerged_branch_blocked(self):
        _git(self.repo, "checkout", "-q", "-b", "feature")
        self._commit("f.md", "work\n", "feature work")
        _git(self.repo, "checkout", "-q", "main")
        r = self._delete("feature")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)

    def test_squash_merged_branch_allowed(self):
        # Two commits on feature; main gets one commit with the same net diff
        # (a squash merge). git cherry alone would miss this; the patch-id path
        # must recognize it.
        _git(self.repo, "checkout", "-q", "-b", "feature")
        self._commit("a.md", "aaa\n", "add a")
        self._commit("b.md", "bbb\n", "add b")
        _git(self.repo, "checkout", "-q", "main")
        (Path(self.repo) / "a.md").write_text("aaa\n")
        (Path(self.repo) / "b.md").write_text("bbb\n")
        _git(self.repo, "add", "a.md", "b.md")
        _git(self.repo, "commit", "-qm", "squash of feature")
        self._push_main()
        r = self._delete("feature")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_rebase_merged_branch_allowed(self):
        # Feature's single commit is cherry-picked onto main (same patch-id).
        _git(self.repo, "checkout", "-q", "-b", "feature")
        tip = self._commit("c.md", "ccc\n", "add c")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "cherry-pick", tip)
        self._push_main()
        r = self._delete("feature")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_true_merged_branch_allowed(self):
        # A real merge: feature tip becomes an ancestor of origin/main.
        _git(self.repo, "checkout", "-q", "-b", "feature")
        self._commit("d.md", "ddd\n", "add d")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "merge", "--no-ff", "-q", "-m", "merge feature", "feature")
        self._push_main()
        r = self._delete("feature")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_unknown_branch_blocked(self):
        r = self._delete("no-such-branch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown branch", r.stderr)

    def test_no_origin_main_blocked(self):
        # A repo with no origin remote cannot verify merge status: fail-safe block.
        solo = os.path.join(self.tmp, "solo")
        subprocess.run(["git", "init", "-q", "-b", "main", solo], check=True)
        _git(solo, "config", "user.email", "t@t.co")
        _git(solo, "config", "user.name", "t")
        (Path(solo) / "x.md").write_text("x\n")
        _git(solo, "add", "x.md")
        _git(solo, "commit", "-qm", "x")
        _git(solo, "branch", "feature")
        r = run_hook("git branch -D feature", cwd=solo)
        self.assertEqual(r.returncode, 2)
        self.assertIn("origin/main", r.stderr)

    def test_merged_delete_force_long_form_allowed(self):
        # The --delete --force spelling gets the same merge check.
        _git(self.repo, "checkout", "-q", "-b", "feature")
        tip = self._commit("e.md", "eee\n", "add e")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "cherry-pick", tip)
        self._push_main()
        r = run_hook("git branch --delete --force feature", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_multiple_branches_one_unmerged_blocked(self):
        # Deleting several at once: any unmerged branch blocks the whole command.
        _git(self.repo, "checkout", "-q", "-b", "merged")
        tip = self._commit("m.md", "mmm\n", "add m")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "cherry-pick", tip)
        self._push_main()
        _git(self.repo, "checkout", "-q", "-b", "unmerged")
        self._commit("u.md", "uuu\n", "add u")
        _git(self.repo, "checkout", "-q", "main")
        r = self._delete("merged unmerged")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)

    def _make_merged(self, name, fname):
        _git(self.repo, "checkout", "-q", "-b", name)
        tip = self._commit(fname, fname + "\n", "add " + fname)
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "cherry-pick", tip)
        self._push_main()

    def test_chained_delete_second_unmerged_blocked(self):
        # Two separate delete commands: the merged one must not let an unmerged
        # one in the same line slip through (the head -n1 regression).
        self._make_merged("merged", "cm.md")
        _git(self.repo, "checkout", "-q", "-b", "unmerged")
        self._commit("cu.md", "uuu\n", "add cu")
        _git(self.repo, "checkout", "-q", "main")
        r = run_hook("git branch -D merged && git branch -D unmerged", cwd=self.repo)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)

    def test_chained_delete_both_merged_allowed(self):
        self._make_merged("m1", "m1.md")
        self._make_merged("m2", "m2.md")
        r = run_hook("git branch -D m1 && git branch -D m2", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_create_then_delete_unmerged_blocked(self):
        # A create segment (git branch <name>) is not a delete and is skipped,
        # but a chained force-delete of an unmerged branch is still checked.
        _git(self.repo, "checkout", "-q", "-b", "unmerged")
        self._commit("x.md", "x\n", "add x")
        _git(self.repo, "checkout", "-q", "main")
        r = run_hook("git branch newfeature && git branch -D unmerged", cwd=self.repo)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)

    def test_merged_delete_with_redirect_allowed(self):
        # A trailing redirection must not read as a second branch and block a
        # legitimate post-merge cleanup.
        self._make_merged("mr", "mr.md")
        r = run_hook("git branch -D mr 2>&1", cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_stale_origin_main_refreshed_before_blocking(self):
        # The merge landed on the remote from somewhere else (another clone, a
        # squash merge on the host), so this repo's origin/main is behind and
        # the branch looks unmerged locally. The guard must fetch and re-check
        # rather than block, so post-merge cleanup never depends on the caller
        # remembering to pull first.
        _git(self.repo, "checkout", "-q", "-b", "remote-squashed")
        self._commit("s1.md", "s1\n", "add s1")
        self._commit("s2.md", "s2\n", "add s2")
        _git(self.repo, "checkout", "-q", "main")
        self._squash_on_remote({"s1.md": "s1\n", "s2.md": "s2\n"})
        # Local origin/main is deliberately NOT refreshed here.
        self.assertNotEqual(
            _git(self.repo, "rev-parse", "origin/main"),
            _git(self.repo, "ls-remote", "origin", "main").split()[0],
        )
        r = self._delete("remote-squashed")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_stale_origin_main_still_blocks_a_truly_unmerged_branch(self):
        # The refresh must not turn into a rubber stamp: after fetching, a
        # branch the remote has never seen is still refused.
        self._squash_on_remote({"other.md": "other\n"})
        _git(self.repo, "checkout", "-q", "-b", "never-pushed")
        self._commit("np.md", "np\n", "add np")
        _git(self.repo, "checkout", "-q", "main")
        r = self._delete("never-pushed")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)

    def test_unreachable_remote_blocks(self):
        # A remote that cannot be contacted must fail closed.
        _git(self.repo, "checkout", "-q", "-b", "orphan")
        self._commit("o.md", "o\n", "add o")
        _git(self.repo, "checkout", "-q", "main")
        _git(self.repo, "remote", "set-url", "origin",
             os.path.join(self.tmp, "does-not-exist.git"))
        r = self._delete("orphan")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)

    def test_hanging_remote_times_out_and_blocks(self):
        # The timeout branch proper: a remote helper that sleeps forever stands
        # in for a remote that accepts the connection and never answers. Without
        # the bound the hook would hang as long as the helper does, so this test
        # both proves the block and would time out the suite on a regression.
        _git(self.repo, "checkout", "-q", "-b", "hangs")
        self._commit("h.md", "h\n", "add h")
        _git(self.repo, "checkout", "-q", "main")
        bindir = Path(self.tmp) / "bin"
        bindir.mkdir()
        helper = bindir / "git-remote-hang"
        helper.write_text("#!/bin/sh\nsleep 300\n")
        helper.chmod(0o755)
        _git(self.repo, "remote", "set-url", "origin", "hang::stalled")
        start = time.monotonic()
        r = run_hook("git branch -D hangs", cwd=self.repo,
                     env={"PATH": f"{bindir}:{os.environ['PATH']}"})
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 9, "the fetch did not actually hang")
        self.assertLess(elapsed, 40, "the timeout did not fire")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)
        # The helper and anything it spawned must be gone, not orphaned.
        left = subprocess.run(
            ["pgrep", "-f", "git-remote-hang"], capture_output=True, text=True
        )
        self.assertNotEqual(left.returncode, 0, f"leaked: {left.stdout}")

    def test_unmerged_delete_with_redirect_blocked_for_right_reason(self):
        # Still blocked, but because it is unmerged -- not because "2>" looked
        # like an unknown branch.
        _git(self.repo, "checkout", "-q", "-b", "unmergedr")
        self._commit("ur.md", "uuu\n", "add ur")
        _git(self.repo, "checkout", "-q", "main")
        r = run_hook("git branch -D unmergedr 2>/dev/null", cwd=self.repo)
        self.assertEqual(r.returncode, 2)
        self.assertIn("not in origin/main", r.stderr)


if __name__ == "__main__":
    unittest.main()
