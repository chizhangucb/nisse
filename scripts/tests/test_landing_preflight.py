"""Tests for scripts/landing_preflight.py (the pre-PR staleness guard).

Run from the repo root: python3 -m pytest scripts/tests/
Each case builds a throwaway git repo in a tempdir with a `main` branch and a
`feature` branch; `main` stands in for the `origin/main` the guard resolves in
real use, and the guard runs with fetch=False so no remote or network is used.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import landing_preflight as lp


class _Repo:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self._env = dict(os.environ,
                         GIT_COMMITTER_DATE="2026-01-01T00:00:00",
                         GIT_AUTHOR_DATE="2026-01-01T00:00:00")
        self.run(["init", "-q", "-b", "main"])
        self.run(["config", "user.email", "test@test.com"])
        self.run(["config", "user.name", "Test"])
        self.write("shared.txt", "base\n")
        self.write("other.txt", "base\n")
        self.commit("base")
        self.run(["checkout", "-q", "-b", "feature"])

    def run(self, args):
        return subprocess.run(["git", *args], cwd=self.dir, env=self._env,
                              capture_output=True, text=True, check=True)

    def write(self, name, body):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
            f.write(body)

    def commit(self, msg):
        self.run(["add", "-A"])
        self.run(["commit", "-q", "-m", msg])

    def head(self):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.dir,
                              capture_output=True, text=True).stdout.strip()

    def status(self):
        return subprocess.run(["git", "status", "--porcelain"], cwd=self.dir,
                              capture_output=True, text=True).stdout.strip()


class TestLandingPreflight(unittest.TestCase):
    def setUp(self):
        self.repo = _Repo()

    def tearDown(self):
        shutil.rmtree(self.repo.dir, ignore_errors=True)

    def _run(self):
        return lp.run_preflight(self.repo.dir, target="main", fetch=False)

    def test_up_to_date_passes(self):
        r = self._run()
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["behind"], 0)
        self.assertEqual(r["conflicts"], [])

    def test_ahead_passes(self):
        self.repo.write("feature-only.txt", "x\n")
        self.repo.commit("feature work")
        r = self._run()
        self.assertEqual(r["verdict"], "pass")
        self.assertEqual(r["behind"], 0)
        self.assertEqual(r["ahead"], 1)

    def test_behind_clean_fails_with_empty_map(self):
        self.repo.run(["checkout", "-q", "main"])
        self.repo.write("main-only.txt", "new on main\n")
        self.repo.commit("main advances")
        self.repo.run(["checkout", "-q", "feature"])
        self.repo.write("feature-only.txt", "y\n")
        self.repo.commit("feature work")
        r = self._run()
        self.assertEqual(r["verdict"], "fail")
        self.assertTrue(r["stale"])
        self.assertEqual(r["behind"], 1)
        self.assertTrue(r["clean"])
        self.assertEqual(r["conflicts"], [])

    def test_behind_conflict_lists_file(self):
        self.repo.run(["checkout", "-q", "main"])
        self.repo.write("shared.txt", "MAIN edit\n")
        self.repo.commit("main edits shared")
        self.repo.run(["checkout", "-q", "feature"])
        self.repo.write("shared.txt", "FEATURE edit\n")
        self.repo.commit("feature edits shared")
        r = self._run()
        self.assertEqual(r["verdict"], "fail")
        self.assertFalse(r["clean"])
        self.assertEqual(r["conflicts"], ["shared.txt"])

    def test_dry_run_restores_tree(self):
        self.repo.run(["checkout", "-q", "main"])
        self.repo.write("shared.txt", "MAIN edit\n")
        self.repo.commit("main edits shared")
        self.repo.run(["checkout", "-q", "feature"])
        self.repo.write("shared.txt", "FEATURE edit\n")
        self.repo.commit("feature edits shared")
        head_before = self.repo.head()
        self._run()
        self.assertEqual(self.repo.head(), head_before)
        self.assertEqual(self.repo.status(), "")

    def test_dirty_tracked_tree_refused(self):
        self.repo.write("shared.txt", "uncommitted edit\n")
        with self.assertRaisesRegex(RuntimeError, "uncommitted tracked"):
            self._run()

    def test_untracked_file_does_not_block(self):
        self.repo.write("scratch.tmp", "untracked junk\n")
        r = self._run()
        self.assertEqual(r["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
