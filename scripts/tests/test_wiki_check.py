#!/usr/bin/env python3
"""Tests for scripts/wiki_check.py.

Every test builds a throwaway wiki in a temp dir and runs the checker against
it, so the real wiki is never scanned. The conforming set asserts a clean pass;
each failure case triggers exactly one named rule.

Run: python3 -m unittest discover -s scripts/tests -v
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import wiki_check as wc  # noqa: E402

TAG_REGISTRY = """# Tag Registry

| Slug | Aliases | Description |
|------|---------|-------------|
| ci_pipeline | | continuous-integration tooling |
| partner | | Partnerships |
"""

# --- conforming pages --------------------------------------------------------

GOOD_SOURCE = """---
type: source
tags: [ci_pipeline]
project: work
created: 2026-08-17
via: fireflies
retrieval: full
distilled:
origin: raw/transcripts/2026-08-17_demo.md
---

# Summary
A short factual digest of the meeting.

# Signals
- **[[entities/acme]]** | acme shipped the integration | #ci_pipeline

# Distilled
(No durable updates.)
"""

GOOD_ENTITY = """---
type: entity
subtype: org
tags: [ci_pipeline]
project: work
created: 2026-08-01
updated: 2026-08-10
confidential:
---

# Current truth (last updated: 2026-08-10)
Acme is a partner. See [[concepts/partnership]].

# Evidence
- 2026-08-01 | acme signed | #ci_pipeline | Source: [[sources/2026-08-17_demo]] (primary)
"""

GOOD_CONCEPT = """---
type: concept
tags: [ci_pipeline]
project: work
created: 2026-08-01
updated: 2026-08-10
confidential:
---

# Current truth (last updated: 2026-08-10)
Partnerships are agreements. See [[entities/acme]].

# Evidence
- 2026-08-02 | partnerships matter | #ci_pipeline | Source: [[sources/2026-08-17_demo]] (primary)
"""

GOOD_CONFIDENTIAL = """---
type: entity
subtype: org
tags: [ci_pipeline]
project: work
created: 2026-08-01
updated: 2026-08-10
confidential: [finance]
---

# Current truth (last updated: 2026-08-10)
Deal context. See [[entities/acme]].

# Evidence
- 2026-08-03 | deal noted | #ci_pipeline | Source: [[sources/2026-08-17_demo]] (primary)
"""

GOOD_ARCHIVE = """---
type: archive
tags: [ci_pipeline]
---

Rotated evidence from [[entities/acme]].

# Evidence
- 2026-07-01 | an older folded claim | #ci_pipeline | Source: [[sources/2026-08-17_demo]] (primary)
"""


def build_conforming(wiki):
    for d in ("sources", "entities", "concepts", "synthesis", "confidential",
              "archive", "metadata", "raw/transcripts", "raw/documents"):
        os.makedirs(os.path.join(wiki, d), exist_ok=True)
    write(wiki, "metadata/tag_registry.md", TAG_REGISTRY)
    write(wiki, "sources/2026-08-17_demo.md", GOOD_SOURCE)
    write(wiki, "entities/acme.md", GOOD_ENTITY)
    write(wiki, "concepts/partnership.md", GOOD_CONCEPT)
    write(wiki, "confidential/deal.md", GOOD_CONFIDENTIAL)
    write(wiki, "archive/concepts/old_partnership.md", GOOD_ARCHIVE)


def write(wiki, rel, text):
    full = os.path.join(wiki, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    return full


def rules_for(violations, page):
    return {v.rule for v in violations if v.page == page}


class WikiCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.wiki = os.path.join(self.tmp, "wiki")
        build_conforming(self.wiki)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_checker(self):
        violations, _checked, found = wc.run(self.wiki)
        self.assertTrue(found, "tag registry should be found")
        return violations

    def assert_only_rule(self, page, rule):
        """The named page is the ONLY page that trips, and it trips exactly `rule`.

        This encodes the acceptance criterion's "one named failure per rule":
        the crafted fixture isolates a single rule, so an accidental second
        violation (on this page or any other) fails the test.
        """
        violations = self.run_checker()
        self.assertEqual({v.page for v in violations}, {page},
                         "only %s should trip, got %s"
                         % (page, sorted({v.page for v in violations})))
        self.assertEqual(rules_for(violations, page), {rule},
                         "expected only %s on %s, got %s"
                         % (rule, page, sorted(rules_for(violations, page))))


class TestConforming(WikiCheckTest):
    def test_clean_set_has_no_violations(self):
        violations = self.run_checker()
        self.assertEqual(violations, [], "conforming wiki should be clean")

    def test_main_exits_zero_and_prints_summary(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = wc.main([self.wiki])
        self.assertEqual(code, 0)
        self.assertIn("0 violation(s)", buf.getvalue())

    def test_json_output_shape(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            wc.main([self.wiki, "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["violations"], [])


class TestFailures(WikiCheckTest):
    def test_project_personal_is_accepted(self):
        # Issue #83: vocabulary is work | personal | health | life.
        write(self.wiki, "sources/2026-08-18_pp.md",
              GOOD_SOURCE.replace("project: work", "project: personal"))
        self.assertEqual(self.run_checker(), [])

    def test_project_personal_projects_is_rejected(self):
        write(self.wiki, "sources/2026-08-18_pp.md",
              GOOD_SOURCE.replace("project: work", "project: personal_projects"))
        self.assert_only_rule("sources/2026-08-18_pp", "frontmatter")

    def test_frontmatter_bad_enum(self):
        write(self.wiki, "sources/2026-08-18_bad.md",
              GOOD_SOURCE.replace("via: fireflies", "via: nope"))
        self.assert_only_rule("sources/2026-08-18_bad", "frontmatter")

    def test_tag_unregistered(self):
        write(self.wiki, "entities/ghost.md",
              GOOD_ENTITY.replace("tags: [ci_pipeline]", "tags: [ghosttag]"))
        self.assert_only_rule("entities/ghost", "tag-unregistered")

    def test_required_sections_missing_distilled(self):
        no_distilled = GOOD_SOURCE.split("# Distilled")[0]
        write(self.wiki, "sources/2026-08-19_nodist.md", no_distilled)
        self.assert_only_rule("sources/2026-08-19_nodist", "required-sections")

    def test_evidence_append_only_out_of_order(self):
        out_of_order = GOOD_ENTITY.replace(
            "- 2026-08-01 | acme signed | #ci_pipeline | Source: "
            "[[sources/2026-08-17_demo]] (primary)",
            "- 2026-08-05 | later | #ci_pipeline | Source: [[sources/2026-08-17_demo]] (primary)\n"
            "- 2026-08-01 | earlier | #ci_pipeline | Source: [[sources/2026-08-17_demo]] (primary)")
        write(self.wiki, "entities/ooo.md", out_of_order)
        self.assert_only_rule("entities/ooo", "evidence-append-only")

    def test_sourced_claim_missing_wikilink(self):
        unsourced = GOOD_ENTITY.replace(
            "Source: [[sources/2026-08-17_demo]] (primary)",
            "Source: a meeting (primary)")
        write(self.wiki, "entities/unsourced.md", unsourced)
        self.assert_only_rule("entities/unsourced", "sourced-claim")

    def test_link_resolve_broken_link(self):
        broken = GOOD_ENTITY.replace("[[concepts/partnership]]", "[[no_such_page]]")
        write(self.wiki, "entities/broken.md", broken)
        self.assert_only_rule("entities/broken", "link-resolve")

    def test_retrieval_declared_missing(self):
        no_retrieval = GOOD_SOURCE.replace("retrieval: full\n", "")
        write(self.wiki, "sources/2026-08-20_noretr.md", no_retrieval)
        self.assert_only_rule("sources/2026-08-20_noretr", "retrieval-declared")

    def test_evidence_synthesis_split(self):
        leaked = GOOD_ENTITY.replace(
            "Acme is a partner. See [[concepts/partnership]].",
            "Acme is a partner. See [[concepts/partnership]].\n"
            "- 2026-08-01 | leaked evidence | #ci_pipeline | Source: "
            "[[sources/2026-08-17_demo]] (primary)")
        write(self.wiki, "entities/leaked.md", leaked)
        self.assert_only_rule("entities/leaked", "evidence-synthesis-split")

    def test_confidential_routing_no_lens(self):
        write(self.wiki, "confidential/open.md",
              GOOD_CONFIDENTIAL.replace("confidential: [finance]", "confidential:"))
        self.assert_only_rule("confidential/open", "confidential-routing")

    def test_signals_thin_no_bullets(self):
        thin = GOOD_SOURCE.replace(
            "- **[[entities/acme]]** | acme shipped the integration | #ci_pipeline\n", "")
        write(self.wiki, "sources/2026-08-21_thin.md", thin)
        self.assert_only_rule("sources/2026-08-21_thin", "signals-thin")

    def test_distilled_marker_missing(self):
        no_marker = GOOD_SOURCE.replace("distilled:\n", "")
        write(self.wiki, "sources/2026-08-22_nomarker.md", no_marker)
        self.assert_only_rule("sources/2026-08-22_nomarker", "distilled-marker")

    def test_unresolved_target_wrong_slug(self):
        write(self.wiki, "entities/widget_factory.md",
              GOOD_ENTITY.replace("[[concepts/partnership]]", "[[entities/acme]]"))
        wrong = GOOD_SOURCE.replace("[[entities/acme]]", "[[widget]]")
        write(self.wiki, "sources/2026-08-23_wrong.md", wrong)
        self.assert_only_rule("sources/2026-08-23_wrong", "unresolved-target")

    def test_word_budget_over_living_cap(self):
        big = GOOD_ENTITY + "\n" + ("word " * 2100)
        write(self.wiki, "entities/big.md", big)
        self.assert_only_rule("entities/big", "word-budget")

    def test_archive_folder_is_walked(self):
        # An archive page with a bad enum must be caught, proving archive/ is
        # walked as a content folder (annex was renamed to archive).
        write(self.wiki, "archive/entities/bad.md",
              GOOD_ARCHIVE.replace("type: archive", "type: nonsense"))
        self.assert_only_rule("archive/entities/bad", "frontmatter")

    def test_annex_type_retired(self):
        # `type: annex` is no longer a known page type; only `archive` is.
        write(self.wiki, "archive/entities/legacy.md",
              GOOD_ARCHIVE.replace("type: archive", "type: annex"))
        self.assert_only_rule("archive/entities/legacy", "frontmatter")

    def test_truncation_skips_non_meeting_source(self):
        # A document-origin source whose mirror exists but has no turns must
        # NOT trip transcript-truncation; those tripwires are for meeting
        # transcripts (raw/transcripts/) only.
        write(self.wiki, "raw/documents/deck.md",
              "# A deck\nSlide one.\nSlide two.\n")
        src = GOOD_SOURCE.replace(
            "origin: raw/transcripts/2026-08-17_demo.md",
            "origin: raw/documents/deck.md")
        write(self.wiki, "sources/2026-08-25_deck.md", src)
        violations = self.run_checker()
        self.assertNotIn("transcript-truncation",
                         rules_for(violations, "sources/2026-08-25_deck"))

    def test_transcript_truncation_backward_jump(self):
        mirror = (
            "# raw mirror\n"
            "Duration: 60 min\n"
            "\n---\n"
            "**Ada Lovelace** [0:00]: hello everyone\n"
            "**Bo Chen** [5:00]: hi there\n"
            "**Ada Lovelace** [2:00]: back in time\n"
        )
        write(self.wiki, "raw/transcripts/2026-08-24_trunc.md", mirror)
        src = GOOD_SOURCE.replace(
            "origin: raw/transcripts/2026-08-17_demo.md",
            "origin: raw/transcripts/2026-08-24_trunc.md")
        write(self.wiki, "sources/2026-08-24_trunc.md", src)
        self.assert_only_rule("sources/2026-08-24_trunc", "transcript-truncation")

    def test_exit_nonzero_on_violation(self):
        write(self.wiki, "entities/broken.md",
              GOOD_ENTITY.replace("[[concepts/partnership]]", "[[no_such_page]]"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = wc.main([self.wiki])
        self.assertEqual(code, 1)


class TestRealWiki(unittest.TestCase):
    """Run the checker over this repo's live wiki root and fail on any
    violation. This is the gate that keeps the real wiki schema-clean: the
    suite goes red the moment a live page drifts out of conformance."""

    def test_live_wiki_has_no_violations(self):
        wiki = wc.DEFAULT_WIKI
        if not os.path.isdir(wiki):
            self.skipTest("no live wiki root at %s" % wiki)
        violations, checked, found = wc.run(wiki)
        self.assertTrue(found, "live wiki tag registry should be found")
        self.assertGreater(checked, 0, "live wiki should have pages to check")
        self.assertEqual(
            violations, [],
            "live wiki has %d violation(s):\n%s" % (
                len(violations),
                "\n".join("%s | %s | %s" % (v.page, v.rule, v.fix)
                          for v in violations)))


if __name__ == "__main__":
    unittest.main()
