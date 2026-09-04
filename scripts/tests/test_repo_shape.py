"""Repo-shape test (issue #26, ADR-0001).

Ported from the upstream. Asserts the repo root matches the target layout and
that no retired folder, hooks directory, retired script, or second root
instructions file comes back.

The test reads git-tracked paths only (`git ls-files`), so generated and
gitignored artifacts (`.tmp/`, `.pytest_cache/`, `.DS_Store`) never make it
flaky. A retired folder trips this only if something commits it again.

Later tickets extend this file with the wiki folder set (#27) and the guards
(#29).
"""
import functools
import os
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent

# The exact set of top-level entries that may be tracked at the repo root.
# Matches the ADR-0001 root layout plus the git/agent infra that carries it.
EXPECTED_ROOT = {
    # instructions + readme
    "AGENTS.md", "CLAUDE.md", "CONTEXT.md", "README.md", "LICENSE",
    # content
    "docs", "context", "wiki", "projects", "contacts", "skills", "scripts",
    # infra. The ADR-0001 root list stops at pyproject.toml; these two are
    # tooling that predates it and still has a caller, so they stay tracked:
    # .coderabbit.yaml configures PR review, .env.example documents the one
    # key wiki_retranscribe.py reads. Delete either and drop it from this set.
    ".claude", ".github", ".gitignore", "pyproject.toml",
    ".coderabbit.yaml", ".env.example",
}

# Folders and files ADR-0001 retired. None may be tracked at the root again.
RETIRED_ROOT = {
    "governance", "records", "plans", "references", "archives", "graphs",
    "spec", "operations.md",
    # a second root instructions file is retired: AGENTS.md is the one map
    "GEMINI.md", "AIOS.md",
}

# Scripts retired with the machinery (#25) and the restructure (#26).
RETIRED_SCRIPTS = {
    "scripts/setup.py",
    "scripts/hygiene.py",
    "scripts/ticket_tracker.py",
    "scripts/daily_maintenance.py",
    "scripts/daily_digest.py",
}

# Paths the retired folders left behind in .gitignore. An ignore rule for a
# folder nobody can commit is a pointer to machinery that no longer exists.
RETIRED_IGNORE_FRAGMENTS = ("governance/", "records/", "graphs/", "plans/")

# context/ is exactly five short templates, nothing else.
EXPECTED_CONTEXT = {
    "about-me.md", "about-business.md", "about-team.md",
    "priorities.md", "goals.md",
}


@functools.lru_cache(maxsize=1)
def tracked_paths():
    """git-tracked paths, read once per test session (one subprocess)."""
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True, text=True, check=True,
    ).stdout
    return tuple(line for line in out.splitlines() if line)


def tracked_toplevel():
    return {p.split("/", 1)[0] for p in tracked_paths()}


def tracked_under(folder):
    prefix = folder + "/"
    return {
        p[len(prefix):] for p in tracked_paths()
        if p.startswith(prefix) and "/" not in p[len(prefix):]
    }


class TestRepoShape(unittest.TestCase):
    def test_root_is_exactly_the_target_layout(self):
        actual = tracked_toplevel()
        extra = actual - EXPECTED_ROOT
        missing = EXPECTED_ROOT - actual
        self.assertFalse(
            extra, f"unexpected tracked entries at repo root: {sorted(extra)}")
        self.assertFalse(
            missing, f"target root entries missing: {sorted(missing)}")

    def test_no_retired_folder_or_file_reappears(self):
        back = tracked_toplevel() & RETIRED_ROOT
        self.assertFalse(
            back, f"retired root entries are tracked again: {sorted(back)}")

    def test_no_retired_script_reappears(self):
        back = set(tracked_paths()) & RETIRED_SCRIPTS
        self.assertFalse(
            back, f"retired scripts are tracked again: {sorted(back)}")

    def test_no_hooks_directory(self):
        # No repo-managed hooks directory: hooks were retired in #25.
        offenders = [
            p for p in tracked_paths()
            if p.startswith("hooks/") or "/hooks/" in p
        ]
        self.assertFalse(
            offenders, f"a hooks directory is tracked again: {offenders}")

    def test_only_one_root_instructions_file(self):
        # AGENTS.md is the single root map; CLAUDE.md is a symlink to it. No
        # third agent-harness instructions file at the root.
        strays = {"GEMINI.md", "AIOS.md"} & tracked_toplevel()
        self.assertFalse(
            strays, f"a second root instructions file is back: {sorted(strays)}")


class TestContextShape(unittest.TestCase):
    def test_context_is_exactly_the_five_templates(self):
        actual = tracked_under("context")
        extra = actual - EXPECTED_CONTEXT
        missing = EXPECTED_CONTEXT - actual
        self.assertFalse(
            extra, f"unexpected files under context/: {sorted(extra)}")
        self.assertFalse(
            missing, f"context templates missing: {sorted(missing)}")

    def test_each_template_carries_a_freshness_note(self):
        for name in sorted(EXPECTED_CONTEXT):
            with self.subTest(file=name):
                text = (REPO / "context" / name).read_text(encoding="utf-8")
                self.assertIn("**Last updated:**", text)


# CLAUDE.md is a git symlink to its sibling AGENTS.md: one instructions file
# per folder, so the harness pointer can never drift. Later tickets add the
# wiki symlinks here.
CLAUDE_POINTERS = ["CLAUDE.md"]


class TestPointers(unittest.TestCase):
    def test_claude_md_files_are_symlinks_to_agents_md(self):
        tracked = tracked_paths()
        for rel in CLAUDE_POINTERS:
            with self.subTest(path=rel):
                path = REPO / rel
                self.assertTrue(path.is_symlink(), f"{rel} is not a symlink")
                self.assertEqual(os.readlink(path), "AGENTS.md")
                self.assertIn(rel, tracked)

    def test_gitignore_names_no_retired_path(self):
        text = (REPO / ".gitignore").read_text(encoding="utf-8")
        offenders = [f for f in RETIRED_IGNORE_FRAGMENTS if f in text]
        self.assertFalse(
            offenders,
            f".gitignore still names retired paths: {sorted(offenders)}")


if __name__ == "__main__":
    unittest.main()
