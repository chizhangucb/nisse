"""Tests for scripts/hygiene_check.py parsing and budget routing.

Run from the repo root: python3 -m pytest scripts/tests/ (or unittest).
"""
import os
import sys
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
        self.assertEqual(hc._budget_for("governance/secrets.md"), 500)
        self.assertEqual(hc._budget_for("governance/gating.md"), 1150)

    def test_uncapped(self):
        self.assertIsNone(hc._budget_for("records/decisions.md"))
        self.assertIsNone(hc._budget_for("references/templates/x.md"))


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


if __name__ == "__main__":
    unittest.main()
