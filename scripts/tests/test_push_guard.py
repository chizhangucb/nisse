"""Tests for the pre-push secret guard (ADR-0001).

Two seams:
  - the hook (scripts/guards/pre-push-secret-scan): given a pushed range on
    stdin, it rejects a secret or a CONFIDENTIAL marker -- both
    unconditionally, since the hook only ever lives in repos others can read.
  - the installer (install_push_guard.py): installs the hook into a public /
    internal repo's own .git/hooks/pre-push, removes it from a private repo,
    and never clobbers a foreign hook.

Hook tests are integration tests: they need git and gitleaks on PATH. They
skip (not fail) when gitleaks is absent, since a machine without it cannot
exercise the scan.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "guards"))

import install_push_guard as ipg  # noqa: E402

GUARDS = Path(__file__).resolve().parent.parent / "guards"
HOOK = GUARDS / "pre-push-secret-scan"
ZERO = "0" * 40
# A realistic-but-fake GitHub token, assembled from two halves so the literal
# never appears in this file. gitleaks flags the joined string wherever the
# fixture writes it, which is the point; but a token-shaped string sitting in
# tracked source is blocked by GitHub push protection (and by our own guard),
# so the file must not contain one.
FAKE_SECRET = "ghp_" + "wWPw5k4aXcaT4fNP0UcnZwJUVFk6LO0pINUx"
HAVE_GITLEAKS = shutil.which("gitleaks") is not None


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def new_repo(tmp):
    git(tmp, "init", "-q")
    git(tmp, "config", "user.email", "test@example.com")
    git(tmp, "config", "user.name", "test")
    return tmp


def commit_file(repo, name, content, msg):
    """Write and commit one file, returning the new HEAD sha."""
    (Path(repo) / name).parent.mkdir(parents=True, exist_ok=True)
    (Path(repo) / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD")


def run_hook(repo, local_sha, remote_sha, env=None):
    """Invoke the hook as git would, feeding one ref line on stdin."""
    stdin = f"refs/heads/main {local_sha} refs/heads/main {remote_sha}\n"
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [str(HOOK)], cwd=repo, input=stdin, capture_output=True, text=True, env=e
    )


@unittest.skipUnless(HAVE_GITLEAKS, "gitleaks not installed")
class HookBehavior(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        new_repo(self.tmp)
        self.base = commit_file(self.tmp, "readme.md", "hello\n", "clean")

    def test_clean_push_allowed(self):
        tip = commit_file(self.tmp, "more.md", "still clean\n", "more")
        r = run_hook(self.tmp, tip, self.base)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_secret_rejected(self):
        tip = commit_file(self.tmp, "creds.env", f"TOKEN={FAKE_SECRET}\n", "leak")
        r = run_hook(self.tmp, tip, self.base)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("secret detected", r.stderr)

    def test_confidential_marker_rejected(self):
        tip = commit_file(self.tmp, "secrets/CONFIDENTIAL", "x\n", "mark")
        r = run_hook(self.tmp, tip, self.base)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CONFIDENTIAL marker", r.stderr)

    def test_root_confidential_marker_rejected(self):
        tip = commit_file(self.tmp, "CONFIDENTIAL", "x\n", "mark")
        r = run_hook(self.tmp, tip, self.base)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CONFIDENTIAL marker", r.stderr)

    def test_filename_containing_confidential_is_allowed(self):
        # A file merely containing the word must not trip the marker check.
        tip = commit_file(self.tmp, "confidentiality.md", "notes\n", "doc")
        r = run_hook(self.tmp, tip, self.base)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_branch_deletion_skipped(self):
        # local_sha all-zero is a deletion: nothing to scan, allowed.
        r = run_hook(self.tmp, ZERO, self.base)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_new_branch_range_scanned(self):
        # remote_sha all-zero (new branch) still catches a secret.
        tip = commit_file(self.tmp, "creds.env", f"TOKEN={FAKE_SECRET}\n", "leak")
        r = run_hook(self.tmp, tip, ZERO)
        self.assertNotEqual(r.returncode, 0)

    def test_confidential_marker_added_then_deleted_in_range_rejected(self):
        # Marker added in one commit and deleted in the tip: the blob still ships
        # in history, so the range check must still reject it.
        (Path(self.tmp) / "secrets").mkdir()
        (Path(self.tmp) / "secrets" / "CONFIDENTIAL").write_text("x\n")
        git(self.tmp, "add", "secrets/CONFIDENTIAL")
        git(self.tmp, "commit", "-qm", "add marker")
        (Path(self.tmp) / "secrets" / "CONFIDENTIAL").unlink()
        git(self.tmp, "add", "-A")
        git(self.tmp, "commit", "-qm", "remove marker")
        tip = git(self.tmp, "rev-parse", "HEAD")
        r = run_hook(self.tmp, tip, self.base)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CONFIDENTIAL marker", r.stderr)

    def test_preexisting_marker_out_of_range_does_not_block(self):
        # A marker introduced by an already-pushed commit is outside the range;
        # a later clean push must not be blocked by it.
        (Path(self.tmp) / "CONFIDENTIAL").write_text("x\n")
        git(self.tmp, "add", "CONFIDENTIAL")
        git(self.tmp, "commit", "-qm", "marker already on remote")
        pushed = git(self.tmp, "rev-parse", "HEAD")
        tip = commit_file(self.tmp, "unrelated.md", "clean fix\n", "clean")
        r = run_hook(self.tmp, tip, pushed)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_missing_remote_sha_falls_back(self):
        # remote_sha not present locally (remote advanced without fetch): the hook
        # must not error out; a clean push still passes.
        tip = commit_file(self.tmp, "more.md", "clean\n", "more")
        bogus = "1" * 40
        r = run_hook(self.tmp, tip, bogus)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_network_call_on_push(self):
        # The hook must not shell out to `gh` (or any network probe) on push.
        # Put a `gh` on PATH that fails loudly if invoked; a clean push must
        # still pass, proving nothing called it.
        bindir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bindir, ignore_errors=True)
        gh = Path(bindir) / "gh"
        gh.write_text("#!/usr/bin/env bash\necho GH_WAS_CALLED >&2\nexit 3\n")
        gh.chmod(0o755)
        tip = commit_file(self.tmp, "clean.md", "no secret\n", "work")
        r = run_hook(self.tmp, tip, self.base,
                     env={"PATH": bindir + os.pathsep + os.environ["PATH"]})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("GH_WAS_CALLED", r.stderr)

    def test_missing_gitleaks_fails_closed(self):
        # A PATH with git+bash but no gitleaks; the hook must refuse, not pass.
        # Built portably: symlink the tools the hook needs into a temp bindir.
        tip = commit_file(self.tmp, "more.md", "clean\n", "more")
        bindir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bindir, ignore_errors=True)
        for tool in ("bash", "git", "grep", "sed", "env", "sort"):
            src = shutil.which(tool)
            if src:
                os.symlink(src, os.path.join(bindir, tool))
        r = run_hook(self.tmp, tip, self.base, env={"PATH": bindir})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("gitleaks not installed", r.stderr)


class Installer(unittest.TestCase):
    """process() decides install/remove per repo from its origin visibility.

    Visibility is mocked so the tests never hit the network; the repo is a real
    throwaway git repo so hook_path resolves the true .git/hooks/pre-push.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        new_repo(self.tmp)
        self.repo = Path(self.tmp)
        git(self.tmp, "remote", "add", "origin",
            "https://github.com/example/example.git")
        self.hook = self.repo / ".git" / "hooks" / "pre-push"
        self._orig_vis = ipg.visibility

    def tearDown(self):
        ipg.visibility = self._orig_vis

    def _fake_visibility(self, value):
        ipg.visibility = lambda slug: value

    def test_installs_into_public_repo(self):
        self._fake_visibility("PUBLIC")
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "public")
        self.assertIn("INSTALLED", detail)
        self.assertTrue(ipg.is_ours(self.hook))
        self.assertTrue(os.access(self.hook, os.X_OK))

    def test_installs_into_internal_repo(self):
        self._fake_visibility("INTERNAL")
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "internal")
        self.assertIn("INSTALLED", detail)
        self.assertTrue(ipg.is_ours(self.hook))

    def test_idempotent(self):
        self._fake_visibility("PUBLIC")
        ipg.process(self.repo)
        before = self.hook.stat().st_mtime_ns
        _, verdict, detail = ipg.process(self.repo)
        self.assertIn("already current", detail)
        self.assertEqual(self.hook.stat().st_mtime_ns, before)

    def test_removes_managed_hook_when_private(self):
        # Public first (installs), then flips private (removes).
        self._fake_visibility("PUBLIC")
        ipg.process(self.repo)
        self.assertTrue(self.hook.exists())
        self._fake_visibility("PRIVATE")
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "private")
        self.assertIn("REMOVED", detail)
        self.assertFalse(self.hook.exists())

    def test_private_repo_with_no_hook_is_noop(self):
        self._fake_visibility("PRIVATE")
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "private")
        self.assertEqual(detail, "no hook needed")
        self.assertFalse(self.hook.exists())

    def test_foreign_hook_left_untouched(self):
        self.hook.parent.mkdir(parents=True, exist_ok=True)
        self.hook.write_text("#!/bin/sh\necho hand-written\n")
        self._fake_visibility("PUBLIC")
        _, verdict, detail = ipg.process(self.repo)
        self.assertIn("SKIP", detail)
        self.assertIn("foreign", detail)
        self.assertIn("hand-written", self.hook.read_text())

    def test_foreign_hook_not_removed_when_private(self):
        # A private repo must not have someone else's hook deleted either.
        self.hook.parent.mkdir(parents=True, exist_ok=True)
        self.hook.write_text("#!/bin/sh\necho hand-written\n")
        self._fake_visibility("PRIVATE")
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(detail, "no hook needed")
        self.assertIn("hand-written", self.hook.read_text())

    def test_dry_run_installs_nothing(self):
        self._fake_visibility("PUBLIC")
        _, _, detail = ipg.process(self.repo, dry_run=True)
        self.assertIn("WOULD INSTALL", detail)
        self.assertFalse(self.hook.exists())

    def test_non_github_remote_skipped(self):
        git(self.tmp, "remote", "set-url", "origin",
            "https://gitlab.com/example/example.git")
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "skip")
        self.assertIn("not a GitHub remote", detail)

    def test_gh_error_skipped(self):
        self._fake_visibility(None)
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "skip")
        self.assertIn("could not read visibility", detail)

    def test_unresolvable_git_dir_skipped(self):
        # A work tree whose .git cannot be resolved must report, not crash.
        self._fake_visibility("PUBLIC")
        orig = ipg.hook_path
        ipg.hook_path = lambda repo: None
        self.addCleanup(setattr, ipg, "hook_path", orig)
        _, verdict, detail = ipg.process(self.repo)
        self.assertEqual(verdict, "public")
        self.assertIn("SKIP", detail)
        self.assertFalse(self.hook.exists())

    def test_no_origin_skipped(self):
        no_remote = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, no_remote, ignore_errors=True)
        new_repo(no_remote)
        _, verdict, detail = ipg.process(Path(no_remote))
        self.assertEqual(verdict, "skip")
        self.assertIn("origin remote", detail)


if __name__ == "__main__":
    unittest.main()
