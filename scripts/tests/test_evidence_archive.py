#!/usr/bin/env python3
"""Tests for scripts/evidence_archive.py.

Every test builds a throwaway wiki tree under a temp dir and runs the helper
against it with a --root override, so the real wiki is never touched.
"""
import io
import os
import re
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import evidence_archive as ea  # noqa: E402

TODAY = date(2026, 8, 11)
CUTOFF = date(2026, 7, 1)  # bullets strictly before July are eligible


def bullet(d, text="claim", tag="ci_pipeline", src="s1", cls="primary"):
    return f"- {d} | {text} | #{tag} | Source: [[{src}]] ({cls})"


def page(evidence_bullets, confidential="", extra_ev_head=""):
    return (
        "---\n"
        "type: entity\n"
        "subtype: product\n"
        "tags: [ci_pipeline, release]\n"
        "project: work\n"
        f"confidential:{(' ' + confidential) if confidential else ''}\n"
        "created: 2026-05-01\n"
        "updated: 2026-06-01\n"
        "---\n\n"
        "# Widget\n\n"
        "Intro line.\n\n"
        "# Current truth (last updated: 2026-06-01)\n\n"
        "- folded already\n\n"
        "# Evidence\n\n"
        + extra_ev_head
        + "\n".join(evidence_bullets) + "\n"
    )


class Tree:
    def __init__(self):
        self.root = tempfile.mkdtemp()

    def write(self, rel, text):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(text)
        return rel

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as f:
            return f.read()

    def exists(self, rel):
        return os.path.exists(os.path.join(self.root, rel))


def run(root, pages, apply, budget=2000, cutoff=CUTOFF):
    buf = io.StringIO()
    code = ea.run(root, list(pages), cutoff, budget, apply, TODAY, out=buf)
    return code, buf.getvalue()


class PathTests(unittest.TestCase):
    def test_archive_path_keeps_wiki_prefix(self):
        # bug 1: the archive path must keep the wiki/ prefix
        self.assertEqual(ea.archive_path_for("wiki/entities/marathon.md"),
                         os.path.join("wiki", "archive", "entities", "marathon.md"))
        self.assertEqual(ea.archive_path_for("wiki/confidential/x.md"),
                         os.path.join("wiki", "archive", "confidential", "x.md"))

    def test_archive_link_target(self):
        self.assertEqual(ea.archive_link_target("wiki/entities/marathon.md"),
                         "archive/entities/marathon")


class FrontmatterTests(unittest.TestCase):
    def test_empty_confidential_does_not_swallow_next_line(self):
        # bug 2: a naive ^field:\s*(.*)$ eats the newline and grabs `created:`
        fm = ea.parse_frontmatter(
            "---\nconfidential:\ncreated: 2026-05-01\n---\nbody\n")
        self.assertEqual(fm.get("confidential"), "")
        self.assertEqual(fm.get("created"), "2026-05-01")
        self.assertEqual(ea.fm_list(fm, "confidential"), [])

    def test_inline_and_block_lists(self):
        fm = ea.parse_frontmatter(
            "---\nconfidential: [finance, legal]\n"
            "tags:\n  - a\n  - b\n---\nx\n")
        self.assertEqual(ea.fm_list(fm, "confidential"), ["finance", "legal"])
        self.assertEqual(ea.fm_list(fm, "tags"), ["a", "b"])


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.t = Tree()

    def test_dry_run_writes_nothing(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 20)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        before = self.t.read(rel)
        code, out = run(self.t.root, [rel], apply=False, budget=60)
        self.assertEqual(code, 0)
        self.assertIn("dry-run", out)
        self.assertEqual(self.t.read(rel), before)
        self.assertFalse(self.t.exists("wiki/archive/entities/w.md"))

    def test_apply_moves_oldest_first_until_under_budget(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        code, out = run(self.t.root, [rel], apply=True, budget=120)
        self.assertEqual(code, 0)
        live = self.t.read(rel)
        archive = self.t.read("wiki/archive/entities/w.md")
        # under budget after
        self.assertLessEqual(len(live.split()), 120)
        # oldest went to archive, newest stayed live (match bullet form, not
        # the bare date which also appears in `created:` frontmatter)
        self.assertIn("- 2026-05-01 |", archive)
        self.assertIn("- 2026-05-20 |", live)
        self.assertNotIn("- 2026-05-20 |", archive)
        self.assertNotIn("- 2026-05-01 |", live)

    def test_conservation_live_plus_archive_equals_total(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        run(self.t.root, [rel], apply=True, budget=120)
        live = self.t.read(rel)
        archive = self.t.read("wiki/archive/entities/w.md")
        live_b = len(re.findall(r"(?m)^- 2026-", live))
        archive_b = len(re.findall(r"(?m)^- 2026-", archive))
        self.assertEqual(live_b + archive_b, 20)

    def test_single_pointer_and_prefix_target(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        run(self.t.root, [rel], apply=True, budget=120)
        live = self.t.read(rel)
        self.assertEqual(live.count("[!note]"), 1)
        self.assertIn("[[archive/entities/w|archived evidence]]", live)

    def test_stale_mid_evidence_pointer_replaced(self):
        # a stale pointer stranded mid-Evidence after a prior partial archival
        stale = ("> [!note] June evidence (5 bullets) rotated to "
                 "[[archive/entities/w|archived evidence]] on 2026-06-15 "
                 "(folded). Later evidence below.\n\n")
        may = [bullet(f"2026-05-{n:02d}") for n in range(1, 11)]
        july = [bullet(f"2026-07-{n:02d}") for n in range(1, 6)]
        # pointer sits between May and July bullets
        body = "\n".join(may) + "\n\n" + stale + "\n".join(july) + "\n"
        full = page([], extra_ev_head="") .rstrip() + "\n" + body
        rel = self.t.write("wiki/entities/w.md", full)
        run(self.t.root, [rel], apply=True, budget=120)
        live = self.t.read(rel)
        # exactly one pointer survives, regenerated at the top of Evidence
        self.assertEqual(live.count("[!note]"), 1)
        self.assertIn("Pre-July Evidence", live)
        self.assertNotIn("June evidence (5 bullets)", live)

    def test_confidential_mark_propagates(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/confidential/w.md",
                           page(bullets, confidential="[finance, legal]"))
        run(self.t.root, [rel], apply=True, budget=120)
        archive = self.t.read("wiki/archive/confidential/w.md")
        self.assertIn("type: archive", archive)
        self.assertIn("confidential: [finance, legal]", archive)
        self.assertIn("source_page: [[w]]", archive)

    def test_empty_confidential_archive_stays_bare(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        run(self.t.root, [rel], apply=True, budget=120)
        archive = self.t.read("wiki/archive/entities/w.md")
        self.assertRegex(archive, r"(?m)^confidential:\s*$")

    def test_protective_callout_blocks_later_bullets(self):
        # a > [!question] callout stops the leading movable run
        warn = ("> [!question] Open: something?\n> body\n\n")
        may_early = [bullet("2026-05-01"), bullet("2026-05-02")]
        may_late = [bullet("2026-05-10"), bullet("2026-05-11")]
        body = ("\n".join(may_early) + "\n\n" + warn + "\n".join(may_late) + "\n")
        full = page([]).rstrip() + "\n" + body
        rel = self.t.write("wiki/entities/w.md", full)
        # budget 0 forces max archival, but callout caps the run at 2
        code, out = run(self.t.root, [rel], apply=True, budget=0)
        archive = self.t.read("wiki/archive/entities/w.md")
        self.assertIn("2026-05-01", archive)
        self.assertIn("2026-05-02", archive)
        self.assertNotIn("2026-05-10", archive)  # behind the callout, not moved
        live = self.t.read(rel)
        self.assertIn("2026-05-10", live)

    def test_appends_to_existing_archive(self):
        existing = (
            "---\ntype: archive\ntags: [ci_pipeline]\nproject: work\nconfidential:\n"
            "created: 2026-06-01\nsource_page: [[w]]\n---\n\n"
            "# w (archived evidence)\n\nIntro.\n\n# Evidence (archived)\n\n"
            + bullet("2026-04-01") + "\n")
        self.t.write("wiki/archive/entities/w.md", existing)
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        run(self.t.root, [rel], apply=True, budget=120)
        archive = self.t.read("wiki/archive/entities/w.md")
        # original bullet kept, new ones appended
        self.assertIn("2026-04-01", archive)
        self.assertIn("2026-05-01", archive)
        # pointer count reflects total archive bullets (existing + moved)
        live = self.t.read(rel)
        m = re.search(r"\((\d+) bullets\)", live)
        archive_b = len(re.findall(r"(?m)^- 2026-", archive))
        self.assertEqual(int(m.group(1)), archive_b)

    def test_budget_uses_whole_file_wordcount(self):
        bullets = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        run(self.t.root, [rel], apply=True, budget=150)
        live = self.t.read(rel)
        # word count is whitespace-split: total = len(text.split())
        self.assertLessEqual(len(live.split()), 150)

    def test_nothing_eligible_flags_not_moves(self):
        # all bullets are after the cutoff -> nothing eligible, page untouched
        bullets = [bullet(f"2026-07-{n:02d}") for n in range(1, 21)]
        rel = self.t.write("wiki/entities/w.md", page(bullets))
        before = self.t.read(rel)
        code, out = run(self.t.root, [rel], apply=True, budget=60)
        self.assertEqual(self.t.read(rel), before)
        self.assertFalse(self.t.exists("wiki/archive/entities/w.md"))

    def test_missing_evidence_section_fails_gracefully(self):
        rel = self.t.write("wiki/entities/w.md",
                           "---\ntype: entity\n---\n\n# W\n\nNo evidence.\n")
        code, out = run(self.t.root, [rel], apply=False)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_discover_finds_over_budget_pages(self):
        big = [bullet(f"2026-05-{n:02d}") for n in range(1, 21)]
        self.t.write("wiki/entities/big.md", page(big))
        self.t.write("wiki/entities/small.md", page([bullet("2026-05-01")]))
        found = ea.discover_pages(self.t.root, CUTOFF, budget=100)
        self.assertIn(os.path.join("wiki", "entities", "big.md"), found)
        self.assertNotIn(os.path.join("wiki", "entities", "small.md"), found)


class CutoffTests(unittest.TestCase):
    def test_default_cutoff_is_first_of_last_month(self):
        self.assertEqual(ea.default_cutoff(date(2026, 8, 11)), date(2026, 7, 1))
        self.assertEqual(ea.default_cutoff(date(2026, 1, 5)), date(2025, 12, 1))


if __name__ == "__main__":
    unittest.main()
