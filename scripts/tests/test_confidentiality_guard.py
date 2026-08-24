"""Tests for scripts/confidentiality_guard.py.

Run from the repo root: python3 -m pytest scripts/tests/ (or unittest).

The guard scans git-tracked files, so each case builds a throwaway git repo in
a tempdir and runs the guard against it. Leak strings are ASSEMBLED at runtime
(never written as a contiguous literal in this source), so this test file
carries no leak of its own even though the guard already self-excludes it.
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import confidentiality_guard as cg

# Assembled so the substring "/Users/chizhang" never appears literally here.
HOME = "/" + "Users" + "/" + "chizhang"
PLACEHOLDER_HOME = "/" + "Users" + "/<you>"
PUBLIC_HANDLE = "chizhang" + "ucb"
LOCAL_TOKEN = "~/chizhang" + "-2"

GITIGNORE = "\n".join([
    ".env",
    "wiki/raw/transcripts/*",
    ".claude/settings.local.json",
    ".claude/state/",
    "records/.sessions_index.lock",
    ".tmp/",
]) + "\n"


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True,
                   capture_output=True, text=True)


def _make_repo(files):
    """Create a temp git repo with `files` (rel -> text) tracked. Always
    includes a valid .gitignore unless the caller overrides it."""
    root = tempfile.mkdtemp()
    _git(root, "init")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    if ".gitignore" not in files:
        files = {".gitignore": GITIGNORE, **files}
    for rel, text in files.items():
        _write(root, rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "fixture")
    return root


class TestGuard(unittest.TestCase):
    def _clean(self, root):
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    def test_clean_tree_passes(self):
        root = _make_repo({"README.md": "hello world\n"})
        self.addCleanup(self._clean, root)
        self.assertEqual(cg.run_checks(root), [])

    def test_leaked_home_path_fails(self):
        root = _make_repo({"notes.md": f"see {HOME}/personal-projects/nisse\n"})
        self.addCleanup(self._clean, root)
        findings = cg.run_checks(root)
        self.assertTrue(any("absolute owner home path" in f for f in findings),
                        findings)

    def test_public_handle_and_local_token_do_not_trip(self):
        root = _make_repo({
            "README.md": (f"clone github.com/{PUBLIC_HANDLE}/nisse\n"
                          f"backup lives at {LOCAL_TOKEN}\n"),
        })
        self.addCleanup(self._clean, root)
        self.assertEqual(cg.run_checks(root), [])

    def test_placeholder_home_does_not_trip(self):
        root = _make_repo({
            "tpl.template": f"__HOME__ your home (macOS: {PLACEHOLDER_HOME})\n",
        })
        self.addCleanup(self._clean, root)
        self.assertEqual(cg.run_checks(root), [])

    def test_self_referential_files_are_excluded(self):
        # A leak string inside the guard's own excluded paths must NOT trip it.
        root = _make_repo({
            "scripts/confidentiality_guard.py": f"# pattern {HOME}\n",
            "plans/2026-08-24-x.md": f"discusses {HOME} as an example\n",
            "archives/plans/old.md": f"historical {HOME}\n",
        })
        self.addCleanup(self._clean, root)
        self.assertEqual(cg.run_checks(root), [])

    def test_missing_gitignore_entry_fails(self):
        gi = GITIGNORE.replace(".env\n", "")
        root = _make_repo({".gitignore": gi, "README.md": "x\n"})
        self.addCleanup(self._clean, root)
        findings = cg.run_checks(root)
        self.assertTrue(any(".gitignore no longer covers '.env'" in f
                            for f in findings), findings)

    def test_unmarked_synthetic_fixture_fails(self):
        rel = cg.SYNTHETIC_FIXTURES[0]
        root = _make_repo({rel: "Weekly sync notes with no marker word.\n"})
        self.addCleanup(self._clean, root)
        findings = cg.run_checks(root)
        self.assertTrue(any("synthetic marker" in f for f in findings), findings)

    def test_marked_synthetic_fixture_passes(self):
        rel = cg.SYNTHETIC_FIXTURES[0]
        root = _make_repo({rel: "FAKE example weekly sync transcript.\n"})
        self.addCleanup(self._clean, root)
        self.assertEqual(cg.run_checks(root), [])


if __name__ == "__main__":
    unittest.main()
