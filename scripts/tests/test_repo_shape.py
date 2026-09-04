"""Repo-shape test (issue #26, ADR-0001).

Ported from the upstream. Asserts the repo root matches the target layout and
that no retired folder, hooks directory, retired script, or second root
instructions file comes back.

The test reads git-tracked paths only (`git ls-files`), so generated and
gitignored artifacts (`.tmp/`, `.pytest_cache/`, `.DS_Store`) never make it
flaky. A retired folder trips this only if something commits it again.

#29 extends this file with the guards.
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

# The exact set of subfolders that may be tracked under wiki/ (#27).
# "annex" was renamed to "archive"; no wiki/annex/ path may be tracked again.
EXPECTED_WIKI = {
    "sources", "entities", "concepts", "synthesis", "archive",
    "confidential", "raw", "metadata", "_templates",
}
RETIRED_WIKI = {"annex", "templates"}

# The exact set of Markdown files that may sit directly under wiki/ (#27).
# AGENTS.md is the one binding schema; CLAUDE.md is a symlink to it. rules.md
# and README.md were folded into the schema.
EXPECTED_WIKI_ROOT_MD = {"AGENTS.md", "CLAUDE.md"}
RETIRED_WIKI_ROOT_MD = {"rules.md", "README.md", "product-contract.md"}

# Every page kind gets a scaffold, and the checker validates them as pages.
EXPECTED_TEMPLATES = {
    "entity.md", "concept.md", "synthesis.md", "archive.md",
    "source-page-general.md", "source-page-meeting.md",
}

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
    """Every tracked path below `folder`, relative and nested ones included.

    Nested, so a `context/notes/scratch.md` shows up as an extra rather than
    slipping past a direct-children-only check.
    """
    prefix = folder + "/"
    return {p[len(prefix):] for p in tracked_paths() if p.startswith(prefix)}


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
            extra, f"unexpected paths under context/: {sorted(extra)}")
        self.assertFalse(
            missing, f"context templates missing: {sorted(missing)}")

    def test_each_template_carries_a_freshness_note(self):
        for name in sorted(EXPECTED_CONTEXT):
            with self.subTest(file=name):
                text = (REPO / "context" / name).read_text(encoding="utf-8")
                self.assertIn("**Last updated:**", text)


# CLAUDE.md files are git symlinks to their sibling AGENTS.md: one instructions
# file per folder, so the harness pointer can never drift.
CLAUDE_POINTERS = ["CLAUDE.md", "wiki/CLAUDE.md", "wiki/confidential/CLAUDE.md"]


def tracked_wiki_subfolders():
    subs = set()
    for p in tracked_paths():
        parts = p.split("/")
        if parts[0] == "wiki" and len(parts) >= 3:
            subs.add(parts[1])
    return subs


def tracked_wiki_root_md():
    return {
        p.split("/")[1] for p in tracked_paths()
        if p.startswith("wiki/") and len(p.split("/")) == 2 and p.endswith(".md")
    }


class TestWikiShape(unittest.TestCase):
    def test_wiki_subfolders_are_exactly_the_target_set(self):
        actual = tracked_wiki_subfolders()
        extra = actual - EXPECTED_WIKI
        missing = EXPECTED_WIKI - actual
        self.assertFalse(
            extra, f"unexpected tracked subfolders under wiki/: {sorted(extra)}")
        self.assertFalse(
            missing, f"target wiki subfolders missing: {sorted(missing)}")

    def test_no_annex_folder(self):
        back = tracked_wiki_subfolders() & RETIRED_WIKI
        self.assertFalse(
            back, f"a retired wiki subfolder is tracked again: {sorted(back)}")

    def test_exactly_one_schema_file_under_wiki(self):
        actual = tracked_wiki_root_md()
        extra = actual - EXPECTED_WIKI_ROOT_MD
        missing = EXPECTED_WIKI_ROOT_MD - actual
        self.assertFalse(
            extra, f"unexpected Markdown at the wiki root: {sorted(extra)}")
        self.assertFalse(
            missing, f"wiki-root schema files missing: {sorted(missing)}")
        back = actual & RETIRED_WIKI_ROOT_MD
        self.assertFalse(
            back, f"a retired wiki schema file is tracked again: {sorted(back)}")

    def test_every_page_kind_has_a_template(self):
        actual = tracked_under("wiki/_templates")
        self.assertEqual(
            actual, EXPECTED_TEMPLATES,
            f"wiki/_templates is not the full scaffold set: {sorted(actual)}")

    def test_the_word_annex_is_gone_from_tracked_text(self):
        # The rename is only real when no file still teaches the old word. The
        # exempt files are the ones that name it precisely to retire it: the
        # glossary's Avoid list, and the two guards asserting it stays gone.
        allowed = {"CONTEXT.md", "scripts/tests/test_repo_shape.py",
                   "scripts/tests/test_wiki_check.py"}
        offenders = []
        for rel in tracked_paths():
            if rel in allowed or not rel.endswith((".md", ".py")):
                continue
            path = REPO / rel
            if path.is_symlink() or not path.exists():
                continue
            if "annex" in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(rel)
        self.assertFalse(offenders, f"'annex' still appears in: {sorted(offenders)}")


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


# The schema makes wiki_ledger.py the only writer of wiki/metadata/*.jsonl.
# Only that module may open one for writing; everything else goes through it.
LEDGER = "scripts/wiki_ledger.py"
JSONL_WRITE_MARKERS = ("O_APPEND", 'open(', "write_text")


class TestLedgerIsTheOnlyJsonlWriter(unittest.TestCase):
    def test_no_script_writes_wiki_metadata_jsonl_directly(self):
        offenders = []
        for rel in tracked_paths():
            if not rel.startswith("scripts/") or not rel.endswith(".py"):
                continue
            if rel == LEDGER or rel.startswith("scripts/tests/"):
                continue
            text = (REPO / rel).read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if ".jsonl" not in line or line.lstrip().startswith("#"):
                    continue
                if any(m in line for m in JSONL_WRITE_MARKERS):
                    offenders.append(f"{rel}:{i}")
        self.assertFalse(
            offenders,
            "wiki/metadata/*.jsonl must be written only through "
            f"{LEDGER}, but these lines open one directly: {offenders}")

    def test_the_ledger_exposes_both_append_verbs(self):
        # The schema names `append-log | append-source` as the CLI contract.
        text = (REPO / LEDGER).read_text(encoding="utf-8")
        for verb in ("append-log", "append-source"):
            with self.subTest(verb=verb):
                self.assertIn(f'"{verb}"', text)


if __name__ == "__main__":
    unittest.main()
