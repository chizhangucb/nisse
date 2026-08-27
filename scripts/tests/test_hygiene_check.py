"""Tests for scripts/hygiene_check.py parsing and budget routing.

Run from the repo root: python3 -m pytest scripts/tests/ (or unittest).
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import hygiene_check as hc


class TestBudgetFor(unittest.TestCase):
    def test_exact_paths(self):
        self.assertEqual(hc._budget_for("AIOS.md"), 2000)
        self.assertEqual(hc._budget_for("wiki/rules.md"), 400)

    def test_skill_budget(self):
        self.assertEqual(hc._budget_for("skills/wiki-ingest/SKILL.md"), 500)

    def test_skill_reference_rules_only(self):
        self.assertEqual(
            hc._budget_for("skills/wiki-ingest/references/ingest-rules.md"), 700)
        self.assertIsNone(
            hc._budget_for("skills/wiki-ingest/references/walkthrough.md"))

    def test_governance_default(self):
        self.assertEqual(hc._budget_for("governance/communication-style.md"), 500)
        self.assertEqual(hc._budget_for("governance/gating.md"), 1150)
        self.assertEqual(hc._budget_for("governance/secrets.md"), 600)

    def test_lessons_exact_budget(self):
        # governance/lessons.md is exact-capped, not the governance/ default
        self.assertEqual(hc._budget_for("governance/lessons.md"), 2000)

    def test_uncapped(self):
        self.assertIsNone(hc._budget_for("records/decisions.jsonl"))
        self.assertIsNone(hc._budget_for("references/templates/x.md"))


class TestLessonsFileCheck(unittest.TestCase):
    """governance/lessons.md ## Entries: each ### entry <=150 words and carries
    a provenance link. Policy prose above ## Entries is never an entry."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hygiene_lessons_test_")
        self._old_root = hc.ROOT
        hc.ROOT = self.tmp
        hc.findings.clear()

    def tearDown(self):
        hc.ROOT = self._old_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_lessons(self, text):
        path = os.path.join(self.tmp, "governance", "lessons.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _messages(self):
        return [f[3] for f in hc.findings]

    def test_over_budget_and_missing_link_flagged(self):
        good = ("### Ship it\n\nAlways do the thing.\n\n"
                "Why: it works.\nProvenance: [decision](records/decisions.jsonl)\n")
        over = ("### Too long\n\n" + ("word " * 200)
                + "\nProvenance: [x](records/decisions.jsonl)\n")
        noprov = "### No link\n\nDo the thing.\nWhy: reasons.\n"
        self._write_lessons(
            "# Lessons\n\n## Rules\n\n- policy prose, not an entry, "
            + ("word " * 200) + "\n\n## Entries\n\n"
            + good + "\n" + over + "\n" + noprov)
        hc._check_lessons_file()
        msgs = self._messages()
        self.assertTrue(any("lesson entry over budget" in m and "Too long" in m
                            for m in msgs), msgs)
        self.assertFalse(any("lesson entry over budget" in m and "Ship it" in m
                             for m in msgs), msgs)
        # policy prose over 150w under ## Rules is not an entry, never flagged
        self.assertFalse(any("lesson entry over budget" in m and "Rules" in m
                             for m in msgs), msgs)
        self.assertTrue(any("missing a provenance link" in m and "No link" in m
                            for m in msgs), msgs)
        self.assertFalse(any("missing a provenance link" in m and "Ship it" in m
                             for m in msgs), msgs)

    def test_missing_file_is_a_noop(self):
        hc._check_lessons_file()
        self.assertEqual(self._messages(), [])


class TestParsers(unittest.TestCase):
    def test_md_table(self):
        rows = hc._parse_md_table(
            "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n")
        self.assertEqual(rows, [{"A": "1", "B": "2"}, {"A": "3", "B": "4"}])

    def test_frontmatter_and_lists(self):
        fm = hc.frontmatter("---\ntype: entity\ntags: [a, b]\n---\nbody\n")
        self.assertEqual(fm["type"], "entity")
        self.assertEqual(hc.fm_list(fm["tags"]), ["a", "b"])

    def test_section(self):
        text = "# Current truth\n\nline one\n\n# Evidence\n\n- x\n"
        self.assertIn("line one", hc.section(text, "# Current truth"))
        self.assertNotIn("- x", hc.section(text, "# Current truth"))

    def test_hub_root_allowlist_matches_contract(self):
        # governance/repo-contract.md allowlists LICENSE/NOTICE at the root
        self.assertIn("LICENSE.md", hc.HUB_ROOT_MD)
        self.assertIn("NOTICE.md", hc.HUB_ROOT_MD)


class TestFloorOrphans(unittest.TestCase):
    """No-orphan floor guarantee: every governance/*.md is a required floor
    pointer or a documented exclusion; a doc that is neither fails HIGH.
    README.md is the folder index, never an orphan."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hygiene_orphans_test_")
        self._old_root = hc.ROOT
        hc.ROOT = self.tmp
        hc.findings.clear()
        os.makedirs(os.path.join(self.tmp, "governance"), exist_ok=True)

    def tearDown(self):
        hc.ROOT = self._old_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_gov(self, name, text="# doc\n"):
        with open(os.path.join(self.tmp, "governance", name), "w",
                  encoding="utf-8") as f:
            f.write(text)

    def _messages(self):
        return [f[3] for f in hc.findings]

    def test_classified_docs_and_readme_are_clean(self):
        # every classified doc present + a README (the folder index) -> no
        # orphan and no stale finding
        for name in list(hc.REQUIRED_FLOOR_POINTERS) + list(
                hc.EXCLUDED_FLOOR_POINTERS):
            self._write_gov(name)
        self._write_gov("README.md", "# Governance index\n")
        hc._check_floor_orphans()
        msgs = self._messages()
        self.assertFalse(any("reachable from no floor" in m for m in msgs), msgs)
        self.assertFalse(any("README.md" in m for m in msgs), msgs)
        self.assertFalse(any("names a missing governance doc" in m
                             for m in msgs), msgs)

    def test_unclassified_doc_fails_high(self):
        for name in list(hc.REQUIRED_FLOOR_POINTERS) + list(
                hc.EXCLUDED_FLOOR_POINTERS):
            self._write_gov(name)
        self._write_gov("neworphan.md", "# unclassified\n")
        hc._check_floor_orphans()
        orphan = [f for f in hc.findings if "reachable from no floor" in f[3]]
        self.assertTrue(orphan, "expected an orphan finding")
        self.assertEqual(orphan[0][0], "HIGH")
        self.assertIn("neworphan.md", orphan[0][3])
        # a classified doc is never called an orphan
        self.assertFalse(any("secrets.md" in f[3] or "routing.md" in f[3]
                             for f in orphan), orphan)

    def test_stale_classification_entry_is_low(self):
        # a classified name with no file present -> LOW stale finding
        self._write_gov("repo-contract.md")
        hc._check_floor_orphans()
        stale = [f for f in hc.findings
                 if "names a missing governance doc" in f[3]]
        self.assertTrue(stale, "expected a stale-entry finding")
        self.assertEqual(stale[0][0], "LOW")


if __name__ == "__main__":
    unittest.main()
