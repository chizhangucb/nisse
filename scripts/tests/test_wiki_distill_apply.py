#!/usr/bin/env python3
"""Tests for wiki_distill_apply.py's log_line validation.

wiki/metadata/log.md's house format is `- YYYY-MM-DD | type | ...`
(wiki-triage/references/triage-rules.md). build_plan() used to append
whatever `package["log_line"]` a distill-drafting agent supplied verbatim,
with no format check -- the actual root cause of a ~620-line corruption in
the real log.md, all missing the leading dash because this script's own
docstring example ("log_line": "2026-08-17 | distill | ...") lacked it too.
These tests lock in the fix: the one deterministic gap (a missing dash) is
auto-corrected, anything else refuses the whole write.

Run: python3 -m unittest discover -s scripts/tests -v
"""

import os
import shutil
import sys
import tempfile
import unittest

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import wiki_distill_apply as da  # noqa: E402

FIXTURE_ROOT = os.path.join(SCRIPTS, "tests", "fixtures", "distill_root")


def minimal_package(log_line):
    return {"date": "2026-08-24", "updates": [], "distilled_lines": {},
            "tags_to_mint": [], "log_line": log_line}


class LogLineValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="distill_apply_")
        self.root = os.path.join(self.tmp, "root")
        shutil.copytree(FIXTURE_ROOT, self.root)
        # the wiki log is now the append-only log.jsonl; build_plan
        # stages a parsed ROW dict under this path, cmd_run appends it.
        self.log_path = os.path.join(self.root, "wiki", "metadata", "log.jsonl")
        with open(self.log_path, "w", encoding="utf-8") as fh:
            fh.write("")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_well_formed_line_passes_through_unchanged(self):
        pkg = minimal_package("- 2026-08-24 | distill | a clean line")
        writes = da.build_plan(self.root, pkg)
        self.assertIn(self.log_path, writes)
        self.assertEqual(writes[self.log_path],
                         {"date": "2026-08-24", "op": "distill",
                          "detail": "a clean line"})

    def test_missing_leading_dash_is_auto_fixed(self):
        pkg = minimal_package("2026-08-24 | distill | forgot the dash")
        writes = da.build_plan(self.root, pkg)
        self.assertEqual(writes[self.log_path],
                         {"date": "2026-08-24", "op": "distill",
                          "detail": "forgot the dash"})

    def test_missing_type_field_refuses_the_whole_write(self):
        pkg = minimal_package("- 2026-08-24 | only one pipe field")
        with self.assertRaises(ValueError):
            da.build_plan(self.root, pkg)

    def test_no_pipes_at_all_refuses(self):
        pkg = minimal_package("2026-08-24 wiki-ingest judgment completed, no pipes")
        with self.assertRaises(ValueError):
            da.build_plan(self.root, pkg)

    def test_refused_write_touches_nothing(self):
        with open(self.log_path, encoding="utf-8") as fh:
            before = fh.read()
        pkg = minimal_package("garbage, not even a date")
        with self.assertRaises(ValueError):
            da.build_plan(self.root, pkg)
        # build_plan never writes to disk itself either way, but confirm the
        # refusal happens before any write is staged for the log file.
        with open(self.log_path, encoding="utf-8") as fh:
            after = fh.read()
        self.assertEqual(before, after)

    def test_empty_log_line_is_a_noop(self):
        pkg = minimal_package("")
        writes = da.build_plan(self.root, pkg)
        self.assertNotIn(self.log_path, writes)


if __name__ == "__main__":
    unittest.main()
