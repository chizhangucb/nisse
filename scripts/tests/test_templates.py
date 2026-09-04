#!/usr/bin/env python3
"""Every wiki template must validate as a page (issue #45).

Each file in wiki/_templates/ is parsed and run through the checker's
frontmatter rules against the real tag registry; a template that does not
conform to the schema is a bug. This is the standing guard that the shipped
templates stay schema-valid as the checker's enums evolve.

Run: python3 -m unittest discover -s scripts/tests -v
"""

import os
import sys
import unittest

SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import wiki_check as wc  # noqa: E402

REPO = os.path.abspath(os.path.join(SCRIPTS, ".."))
TEMPLATES = os.path.join(REPO, "wiki", "_templates")
REGISTRY = os.path.join(REPO, "wiki", "metadata", "tag_registry.md")

EXPECTED_TEMPLATES = {
    "source-page-general.md",
    "source-page-meeting.md",
    "entity.md",
    "concept.md",
    "synthesis.md",
    "archive.md",
}


# The source templates are wiki-ingest scaffolds: their required frontmatter is
# left blank on purpose for ingest to fill (see wiki_ingest.render_source_scaffold).
# So they must MATCH the schema (no bad enums, correct option hints) but may carry
# blank required fields; the four added templates validate outright.
SCAFFOLD_TEMPLATES = {"source-page-general.md", "source-page-meeting.md"}


def template_files():
    return sorted(n for n in os.listdir(TEMPLATES) if n.endswith(".md"))


def frontmatter_violations(name):
    known_tags, found = wc.load_tag_registry(REGISTRY)
    assert found, "tag registry must load"
    with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
        text = fh.read()
    data, ok = wc.parse_frontmatter(text)
    out = []
    wc.check_frontmatter("_templates/" + name[:-3], data, ok, known_tags, out)
    return out


class TestTemplates(unittest.TestCase):
    def test_expected_templates_present(self):
        self.assertEqual(set(template_files()), EXPECTED_TEMPLATES)

    def test_added_templates_validate_as_pages(self):
        for name in sorted(EXPECTED_TEMPLATES - SCAFFOLD_TEMPLATES):
            with self.subTest(template=name):
                out = frontmatter_violations(name)
                self.assertEqual(
                    out, [], "template %s has frontmatter violations: %s"
                    % (name, [v.fix for v in out]))

    def test_source_scaffolds_carry_the_corrected_option_hints(self):
        # Issue #83: `personal` is the value, `personal_projects` and the
        # venture slug are retired; the generic confidential lenses are present.
        for name in sorted(SCAFFOLD_TEMPLATES):
            with self.subTest(template=name):
                with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertIn("| personal |", text)
                self.assertNotIn("personal_projects", text)
                self.assertNotIn("venture-slug", text)
                self.assertIn("finance", text)


if __name__ == "__main__":
    unittest.main()
