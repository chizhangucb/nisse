#!/usr/bin/env python3
"""Tests for the mechanical ingest half. Fixtures and tmp dirs only, zero network.

Every Fireflies call goes through an injected fetcher that reads a canned
GraphQL payload, so no test can reach the live API.
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
sys.path.insert(0, os.path.dirname(HERE))

import wiki_check as tt  # noqa: E402
import wiki_ingest as wi  # noqa: E402
import wiki_ledger as al  # noqa: E402

CANNED = json.load(open(os.path.join(FIXTURES, "ingest_fireflies_response.json")))


def make_fetcher(list_ids=("FF1", "FF2")):
    """Injected stand-in for the GraphQL client. Never touches the network."""
    def fetcher(query, variables=None):
        if "transcripts(" in query:
            rows = [r for r in CANNED["listing"]["transcripts"] if r["id"] in list_ids]
            for extra in list_ids:
                if extra not in [r["id"] for r in rows]:
                    row = dict(CANNED["transcripts"][extra])
                    row.pop("sentences", None)
                    rows.append(row)
            return {"transcripts": rows}
        return {"transcript": CANNED["transcripts"][variables["id"]]}
    return fetcher


class AdapterTests(unittest.TestCase):
    def test_fireflies_normalization(self):
        result = wi.fetch_fireflies("2026-07-30", "2026-07-30", fetcher=make_fetcher(("FF1",)))
        self.assertEqual(len(result.meetings), 1)
        m = result.meetings[0]
        self.assertEqual(m.source, "fireflies")
        self.assertEqual(m.date, "2026-07-30")
        self.assertEqual(m.duration_min, 31)
        self.assertEqual(m.speakers, ["Ada Lovelace", "Bo Chen"])
        self.assertEqual(m.attendees, ["Ada Lovelace", "Bo Chen"])
        self.assertEqual(m.sentence_count, 7)
        self.assertEqual(len(wi.merge_turns(m.sentences)), 6)
        self.assertTrue(m.extra_metadata["fred_joined"])

    def test_fireflies_date_range_excludes_outside_meetings(self):
        result = wi.fetch_fireflies("2026-07-01", "2026-07-02", fetcher=make_fetcher(("FF1",)))
        self.assertEqual(result.meetings, [])

    def test_unknown_source_is_rejected_by_the_adapter_seam(self):
        # The seam is a closed choice list: a source with no mechanical adapter
        # is landed by the skill via the scaffold path, never invented here.
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            wi.main(["--since", "2026-07-24", "--until", "2026-07-31",
                     "--source", "nonesuch"])
        self.assertIn("invalid choice", err.getvalue())


def make_paged_fetcher(total, calls=None):
    """List fetcher that honors `skip`/`limit`, so pagination can be exercised.

    Returns `total` synthetic in-window rows across as many pages as it takes.
    Never returns sentences; use with_sentences=False.
    """
    def fetcher(query, variables=None):
        if "transcripts(" in query:
            if calls is not None:
                calls.append(variables.get("skip", 0))
            skip = variables.get("skip", 0)
            limit = variables["limit"]
            rows = [{"id": f"P{i}", "title": "Paged Meeting",
                     "dateString": "2026-05-10T12:00:00.000Z", "duration": 30,
                     "speakers": [{"name": "X"}], "meeting_attendees": []}
                    for i in range(skip, min(skip + limit, total))]
            return {"transcripts": rows}
        raise AssertionError("no sentence fetch expected in a listing test")
    return fetcher


class PaginationTests(unittest.TestCase):
    def test_pagination_walks_every_page(self):
        calls = []
        result = wi.fetch_fireflies("2026-05-01", "2026-05-31",
                                    fetcher=make_paged_fetcher(110, calls),
                                    with_sentences=False)
        self.assertEqual(len(result.meetings), 110)
        # every page distinct: no row fetched twice
        ids = {m.provider_id for m in result.meetings}
        self.assertEqual(len(ids), 110)
        self.assertEqual(calls, [0, 50, 100])   # skip advanced by LIST_LIMIT

    def test_single_short_page_stops_after_one_call(self):
        calls = []
        result = wi.fetch_fireflies("2026-05-01", "2026-05-31",
                                    fetcher=make_paged_fetcher(10, calls),
                                    with_sentences=False)
        self.assertEqual(len(result.meetings), 10)
        self.assertEqual(calls, [0])

    def test_exactly_one_full_page_probes_the_next(self):
        calls = []
        result = wi.fetch_fireflies("2026-05-01", "2026-05-31",
                                    fetcher=make_paged_fetcher(wi.LIST_LIMIT, calls),
                                    with_sentences=False)
        self.assertEqual(len(result.meetings), wi.LIST_LIMIT)
        # a full first page forces a second, empty page to confirm the end
        self.assertEqual(calls, [0, wi.LIST_LIMIT])


class ReprocessEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sources_dir = os.path.join(self.tmp, "sources")
        os.makedirs(self.sources_dir)
        os.makedirs(os.path.join(self.tmp, "wiki", "metadata"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _seed_sources(self, rows):
        for slug, raw in rows:
            al.append_wiki_source(self.tmp, month="2026-05", slug=slug, raw=raw)

    def test_only_garble_ledger_lines_are_candidates(self):
        self._seed_sources([
            ("2026-05-15_lei_owner_weekly",
             "[[2026-05-15_lei_owner_weekly]] | meeting 2026-05-15, Lei | work | "
             "verbatim | hiring | Garbled capture: BD plus perf critique"),
            ("2026-05-29_david_owner_sync",
             "2026-05-29_david_owner_sync | ledger | silent capture, no raw, no content"),
            ("2026-05-30_wwn_rzts_xwi",
             "2026-05-30_wwn_rzts_xwi | ledger, raw only | truncated near-empty capture"),
            ("2026-05-08_maggie_owner_catchup",
             "[[2026-05-08_maggie_owner_catchup]] | meeting 2026-05-08, the owner/Maggie | work "
             "| verbatim | | Garbled; attempted unrecoverable earlier, healed"),
        ])
        _full, _series, candidates = wi.read_index_slugs(self.tmp)
        self.assertIn("2026-05-15_lei_owner_weekly", candidates)
        self.assertNotIn("2026-05-29_david_owner_sync", candidates)     # silent, no garble
        self.assertNotIn("2026-05-30_wwn_rzts_xwi", candidates)       # truncated, no garble
        self.assertNotIn("2026-05-08_maggie_owner_catchup", candidates)  # unrecoverable word

    def test_eligible_excludes_slugs_that_already_have_a_source_page(self):
        candidates = {"2026-05-15_lei_owner_weekly", "2026-05-13_chase_owner"}
        with open(os.path.join(self.sources_dir, "2026-05-13_chase_owner.md"), "w") as f:
            f.write("landed page")
        eligible = wi.reprocess_eligible_slugs(candidates, self.sources_dir)
        self.assertEqual(eligible, {"2026-05-15_lei_owner_weekly"})


class DedupeTests(unittest.TestCase):
    def _meetings(self, ids):
        fetcher = make_fetcher(ids)
        return wi.fetch_fireflies("2026-07-30", "2026-07-30", fetcher=fetcher).meetings

    def test_winner_is_the_capture_with_the_most_sentences(self):
        kept, flags = wi.dedupe_captures(self._meetings(("FF1", "FF2")))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].provider_id, "FF1")
        self.assertEqual(flags, [])
        self.assertEqual(kept[0].extra_metadata["excluded_captures"], ["FF2"])

    def test_loser_with_unique_segment_is_flagged_not_dropped(self):
        kept, flags = wi.dedupe_captures(self._meetings(("FF1", "FF3")))
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(flags), 1)
        self.assertIn("NEEDS-JUDGMENT", flags[0]["reason"])
        self.assertTrue(kept[0].extra_metadata["dedupe_conflict"])

    def test_fred_joined_breaks_a_sentence_count_tie(self):
        a = wi.NormalizedMeeting("fireflies", "A", "Tie Meeting", "2026-07-30", 30, [], ["X"],
                                 [("X", 0, "one")], "", {"fred_joined": False})
        b = wi.NormalizedMeeting("fireflies", "B", "Tie Meeting", "2026-07-30", 30, [], ["X"],
                                 [("X", 0, "one")], "", {"fred_joined": True})
        kept, _ = wi.dedupe_captures([a, b])
        self.assertEqual(kept[0].provider_id, "B")

    def test_non_strict_dedupe_skips_the_coverage_judgment(self):
        kept, flags = wi.dedupe_captures(self._meetings(("FF1", "FF3")), strict=False)
        self.assertEqual(len(kept), 1)
        self.assertEqual(flags, [])

    def test_distinct_meetings_are_not_merged(self):
        a = wi.NormalizedMeeting("fireflies", "A", "One", "2026-07-30", 30, [], ["X"],
                                 [("X", 0, "one")], "", {})
        b = wi.NormalizedMeeting("fireflies", "B", "Two", "2026-07-30", 30, [], ["X"],
                                 [("X", 0, "two")], "", {})
        kept, flags = wi.dedupe_captures([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(flags, [])


class FormattingTests(unittest.TestCase):
    def test_consecutive_same_speaker_sentences_merge_into_one_turn(self):
        turns = wi.merge_turns([("Ada", 10, "One."), ("Ada", 18, "Two."), ("Bo", 30, "Three.")])
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0], ("Ada", 10, "One. Two."))

    def test_raw_mirror_header_and_turn_format(self):
        m = wi.fetch_fireflies("2026-07-30", "2026-07-30",
                               fetcher=make_fetcher(("FF1",))).meetings[0]
        text = wi.render_raw_mirror(m)
        self.assertIn("# Fixture Weekly Sync", text)
        self.assertIn("- Date: 2026-07-30", text)
        self.assertIn("- Duration: 31 min", text)
        self.assertIn("- Speakers: Ada Lovelace, Bo Chen", text)
        self.assertIn("- Invited: Ada Lovelace, Bo Chen", text)
        self.assertIn("- Captured by: Fireflies (API ingest)", text)
        self.assertIn("- Source: https://app.fireflies.ai/view/FF1", text)
        self.assertIn("\n---\n", text)
        body = text.split("\n---\n", 1)[1]
        first = body.split("\n\n")[0]
        self.assertTrue(first.startswith("**Ada Lovelace** [00:10]: Opening the sync."))
        self.assertIn("Two sentences from the same speaker.", first)
        self.assertIn("**Bo Chen** [29:50]: Closing.", body)

    def test_slugify_drops_bracketed_prefixes_and_punctuation(self):
        self.assertEqual(wi.slugify("Weekly GTM & Partnership Meeting"),
                         "weekly_gtm_partnership_meeting")
        self.assertEqual(wi.slugify("[Placeholder] Sync"), "sync")

    def test_stamp_uses_hours_past_an_hour(self):
        self.assertEqual(wi.stamp(70), "01:10")
        self.assertEqual(wi.stamp(3671), "1:01:11")


class ClobberGuardTests(unittest.TestCase):
    def test_existing_raw_file_stops_the_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2026-07-30_fixture.md")
            wi.write_raw_mirror(path, "first")
            with self.assertRaises(wi.ClobberError):
                wi.write_raw_mirror(path, "second")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "first")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "2026-07-30_fixture.md")
            wi.write_raw_mirror(path, "body", dry_run=True)
            self.assertFalse(os.path.exists(path))


class SlugTests(unittest.TestCase):
    def test_known_series_slug_is_reused(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Project DecaCorn Weekly", "2026-07-30",
                                 30, [], ["X"], [("X", 0, "hi")], "", {})
        slug, reason = wi.resolve_series_slug(m, {"project_decacorn_weekly": 4}, [])
        self.assertEqual(slug, "project_decacorn_weekly")
        self.assertIsNone(reason)

    def test_title_containing_an_established_series_reuses_that_series(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Project DecaCorn Weekly", "2026-07-30",
                                 30, [], ["X"], [("X", 0, "hi")], "", {})
        slug, reason = wi.resolve_series_slug(m, {"decacorn_weekly": 5}, [])
        self.assertEqual(slug, "decacorn_weekly")
        self.assertIsNone(reason)

    def test_same_letters_different_word_split_reuses_the_series(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Hiring Stand-up", "2026-07-30",
                                 30, [], ["X"], [("X", 0, "hi")], "", {})
        slug, reason = wi.resolve_series_slug(m, {"hiring_standup": 9}, [])
        self.assertEqual(slug, "hiring_standup")
        self.assertIsNone(reason)

    def test_partial_token_never_counts_as_a_series_match(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Decacornish Weekly", "2026-07-30",
                                 30, [], ["X"], [("X", 0, "hi")], "", {})
        slug, reason = wi.resolve_series_slug(m, {"decacorn_weekly": 5}, [])
        self.assertEqual(slug, "decacornish_weekly")
        self.assertIsNone(reason)

    def test_two_contained_series_is_needs_judgment(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Hiring Stand-up Weekly", "2026-07-30",
                                 30, [], ["X"], [("X", 0, "hi")], "", {})
        slug, reason = wi.resolve_series_slug(
            m, {"hiring_stand": 3, "stand_up_weekly": 4}, [])
        self.assertIn("ambiguous", reason)

    def test_same_attendee_set_reuses_a_single_prior_series(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Untitled Meet", "2026-07-30", 30,
                                 [], ["the owner Zhang", "Lei Lei"], [("X", 0, "hi")], "", {})
        prior = [("lei_owner_weekly", frozenset({"the owner Zhang", "Lei Lei"}))]
        slug, reason = wi.resolve_series_slug(m, {"lei_owner_weekly": 3}, prior)
        self.assertEqual(slug, "lei_owner_weekly")
        self.assertIsNone(reason)

    def test_two_candidate_series_is_needs_judgment(self):
        m = wi.NormalizedMeeting("fireflies", "A", "Untitled Meet", "2026-07-30", 30,
                                 [], ["the owner Zhang", "Lei Lei"], [("X", 0, "hi")], "", {})
        prior = [("lei_owner_weekly", frozenset({"the owner Zhang", "Lei Lei"})),
                 ("lei_owner_sync", frozenset({"the owner Zhang", "Lei Lei"}))]
        slug, reason = wi.resolve_series_slug(
            m, {"lei_owner_weekly": 3, "lei_owner_sync": 2}, prior)
        self.assertIn("ambiguous", reason)


class IndexAndLogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "wiki", "metadata"))
        self.meeting = wi.NormalizedMeeting("fireflies", "A", "Fixture Weekly Sync",
                                            "2026-07-30", 31, [], ["Ada Lovelace"],
                                            [("Ada Lovelace", 0, "hi")],
                                            "https://app.fireflies.ai/view/A", {})

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_append_writes_a_source_row(self):
        line = wi.append_index_line(self.meeting, "2026-07-30_fixture_weekly_sync",
                                    self.tmp)
        rows = al.read_wiki_sources(self.tmp)
        self.assertEqual([r["slug"] for r in rows], ["2026-07-30_fixture_weekly_sync"])
        self.assertEqual(rows[0]["month"], "2026-07")
        self.assertIn("[[2026-07-30_fixture_weekly_sync]] | meeting 2026-07-30, "
                      "Fixture Weekly Sync | work | verbatim |", rows[0]["raw"])
        # the returned value is still the markdown-style "- ..." line
        self.assertTrue(line.startswith("- [[2026-07-30_fixture_weekly_sync]]"))

    def test_both_slugs_land_as_rows(self):
        older = wi.NormalizedMeeting("fireflies", "B", "Older Sync", "2026-07-28", 20, [],
                                     ["Ada Lovelace"], [("Ada Lovelace", 0, "hi")], "", {})
        wi.append_index_line(older, "2026-07-28_older_sync", self.tmp)
        wi.append_index_line(self.meeting, "2026-07-30_fixture_weekly_sync", self.tmp)
        slugs = {r["slug"] for r in al.read_wiki_sources(self.tmp)}
        self.assertEqual(slugs, {"2026-07-28_older_sync", "2026-07-30_fixture_weekly_sync"})

    def test_index_append_is_idempotent_by_hard_stop(self):
        wi.append_index_line(self.meeting, "2026-07-30_fixture_weekly_sync", self.tmp)
        with self.assertRaises(wi.ClobberError):
            wi.append_index_line(self.meeting, "2026-07-30_fixture_weekly_sync", self.tmp)

    def test_replace_appends_a_fresh_row_as_current_state(self):
        slug = "2026-07-30_fixture_weekly_sync"
        al.append_wiki_source(self.tmp, month="2026-07", slug=slug,
                              raw=f"{slug} | ledger | Garbled capture: something")
        line = wi.append_index_line(self.meeting, slug, self.tmp, replace=True)
        # the append-log keeps the garble row as history; the fresh row is last
        rows = [r for r in al.read_wiki_sources(self.tmp) if r["slug"] == slug]
        self.assertEqual(len(rows), 2)
        self.assertNotIn("Garbled capture", rows[-1]["raw"])
        self.assertEqual("- " + rows[-1]["raw"], line)
        # read_index_slugs dedups to the fresh row, so the slug is no candidate now
        full, _series, candidates = wi.read_index_slugs(self.tmp)
        self.assertIn(slug, full)
        self.assertNotIn(slug, candidates)

    def test_log_line_format(self):
        line = wi.append_log_line(self.meeting, "2026-07-30_fixture_weekly_sync",
                                  self.tmp, today="2026-07-31")
        self.assertEqual(line, "- 2026-07-31 | ingest | [[2026-07-30_fixture_weekly_sync]] "
                               "landed via fireflies; scaffold pending judgment half")
        rows = al.read_wiki_log(self.tmp)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-07-31")
        self.assertEqual(rows[0]["op"], "ingest")
        self.assertIn("[[2026-07-30_fixture_weekly_sync]] landed via fireflies",
                      rows[0]["detail"])


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.meeting = wi.fetch_fireflies("2026-07-30", "2026-07-30",
                                          fetcher=make_fetcher(("FF1",))).meetings[0]

    def test_frontmatter_is_filled_mechanically_and_judgment_left_blank(self):
        text = wi.render_source_scaffold(self.meeting, "2026-07-30_fixture_weekly_sync",
                                         wi.TEMPLATE, today="2026-07-31")
        self.assertIn("type: source", text)
        self.assertIn("project: work", text)
        self.assertIn("created: 2026-07-30", text)
        self.assertIn("ingested: 2026-07-31", text)
        self.assertIn("via: fireflies", text)
        self.assertIn("origin: raw/transcripts/2026-07-30_fixture_weekly_sync.md", text)
        self.assertIn("participants: [Ada Lovelace, Bo Chen]", text)
        for blank in ("meeting_type:", "context:", "confidential:", "distilled:", "tags:"):
            self.assertRegex(text, r"(?m)^" + blank + r"\s*(#.*)?$|^" + blank + r"\s*\[\]")

    def test_body_carries_todo_markers_and_the_transcript_pointer(self):
        text = wi.render_source_scaffold(self.meeting, "2026-07-30_fixture_weekly_sync",
                                         wi.TEMPLATE, today="2026-07-31")
        self.assertIn("TODO wiki-ingest judgment half", text)
        self.assertIn("Fireflies: https://app.fireflies.ai/view/FF1", text)
        self.assertIn("Raw mirror: `wiki/raw/transcripts/"
                      "2026-07-30_fixture_weekly_sync.md`", text)
        self.assertIn("Excluded captures: none", text)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for sub in ("raw", "sources"):
            os.makedirs(os.path.join(self.tmp, sub))
        os.makedirs(os.path.join(self.tmp, "wiki", "metadata"))
        self.ctx = {
            "index_slugs": set(),
            "series_counts": {},
            "prior_pages": [],
            "scorer": wi.load_quality_scorer(),
            "raw_dir": os.path.join(self.tmp, "raw"),
            "sources_dir": os.path.join(self.tmp, "sources"),
            "hub": self.tmp,
            "template": wi.TEMPLATE,
            "today": "2026-07-31",
            "dry_run": False,
            "write_scaffold": True,
            "run_checks": tt.run_checks,
        }
        self.meeting = wi.fetch_fireflies("2026-07-30", "2026-07-30",
                                          fetcher=make_fetcher(("FF1",))).meetings[0]

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_full_landing_writes_every_artifact(self):
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "LANDED", rec["notes"])
        self.assertTrue(os.path.isfile(os.path.join(
            self.ctx["raw_dir"], "2026-07-30_fixture_weekly_sync.md")))
        self.assertTrue(os.path.isfile(os.path.join(
            self.ctx["sources_dir"], "2026-07-30_fixture_weekly_sync.md")))
        slugs = {r["slug"] for r in al.read_wiki_sources(self.tmp)}
        self.assertIn("2026-07-30_fixture_weekly_sync", slugs)
        self.assertTrue(any(r["op"] == "ingest" for r in al.read_wiki_log(self.tmp)))

    def test_already_ingested_slug_hard_stops(self):
        self.ctx["index_slugs"].add("2026-07-30_fixture_weekly_sync")
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "SKIPPED")
        self.assertIn("already ingested", rec["notes"][0])
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_dry_run_lands_nothing(self):
        self.ctx["dry_run"] = True
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "LANDED")
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))
        self.assertEqual(al.read_wiki_sources(self.tmp), [])

    def test_tripwire_failure_blocks_index_and_log(self):
        self.meeting.duration_min = 200          # capture covers a fraction of it
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FAILED")
        self.assertEqual(al.read_wiki_sources(self.tmp), [])
        # the tripwire runs before the raw mirror is written, so a
        # FAIL must never leave a mirror orphaned on disk with no index entry.
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))
        self.assertEqual(al.read_wiki_log(self.tmp), [])

    def test_tripwire_failure_retries_cleanly_not_clobber_guard(self):
        # regression: since a tripwire FAIL no longer writes the raw
        # mirror, a retry (e.g. next weekly run, same meeting still "missing"
        # from the index) re-hits the same tripwire FAIL, never a clobber
        # guard. That's what makes the failure self-consistent instead of
        # permanently stuck.
        self.meeting.duration_min = 200
        first = wi.land_meeting(self.meeting, self.ctx)
        second = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(first["status"], "FAILED")
        self.assertEqual(second["status"], "FAILED")
        self.assertTrue(any("tripwire FAIL" in n for n in second["notes"]))
        self.assertFalse(any("clobber guard" in n for n in second["notes"]))
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_dedupe_conflict_stops_before_any_write(self):
        self.meeting.extra_metadata["dedupe_conflict"] = True
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FLAGGED")
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_garbled_capture_is_flagged_and_never_mirrored(self):
        speakers = ["Ada Lovelace", "Bo Chen"]
        garbled = [(speakers[i % 2], i * 300, "Uh.") for i in range(6)]
        self.meeting.sentences = garbled
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FLAGGED")
        self.assertIn("garbled", rec["notes"][0])
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_scaffold_exists_fails_before_raw_mirror(self):
        # a pre-existing source page must FAIL before the raw mirror is
        # written, or the mirror is orphaned with no index entry (raw/ immutable,
        # so a retry clobber-guards forever). Same shape as 's tripwire.
        slug = "2026-07-30_fixture_weekly_sync"
        with open(os.path.join(self.ctx["sources_dir"], f"{slug}.md"),
                  "w", encoding="utf-8") as f:
            f.write("pre-existing source page\n")
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FAILED")
        self.assertTrue(any("source page already exists" in n for n in rec["notes"]))
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))
        self.assertEqual(al.read_wiki_sources(self.tmp), [])
        self.assertEqual(al.read_wiki_log(self.tmp), [])

    def test_scaffold_exists_retries_cleanly_not_clobber_guard(self):
        # No mirror was written, so a retry re-hits the same clean FAIL, never a
        # clobber guard on an orphaned raw mirror.
        slug = "2026-07-30_fixture_weekly_sync"
        with open(os.path.join(self.ctx["sources_dir"], f"{slug}.md"),
                  "w", encoding="utf-8") as f:
            f.write("pre-existing source page\n")
        first = wi.land_meeting(self.meeting, self.ctx)
        second = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(first["status"], "FAILED")
        self.assertEqual(second["status"], "FAILED")
        self.assertFalse(any("clobber guard" in n for n in second["notes"]))
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_index_carries_slug_fails_before_raw_mirror(self):
        # the index clobber guard must FAIL before the raw mirror is
        # written. Drift case: the on-disk shard carries the slug but the
        # in-memory index_slugs set does not, so the SKIPPED short-circuit
        # doesn't catch it and control reaches the index guard.
        slug = "2026-07-30_fixture_weekly_sync"
        wi.append_index_line(self.meeting, slug, self.ctx["hub"])
        self.assertTrue(wi.index_carries_slug(slug, self.ctx["hub"]))
        self.assertNotIn(slug, self.ctx["index_slugs"])
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FAILED")
        self.assertTrue(any("index guard" in n for n in rec["notes"]))
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))
        self.assertFalse(os.listdir(self.ctx["sources_dir"]))
        self.assertEqual(al.read_wiki_log(self.tmp), [])

    def test_index_carries_slug_retries_cleanly_not_clobber_guard(self):
        # No mirror written on the index-guard FAIL, so a retry re-hits the same
        # clean index-guard FAIL, never a clobber guard on an orphaned mirror.
        slug = "2026-07-30_fixture_weekly_sync"
        wi.append_index_line(self.meeting, slug, self.ctx["hub"])
        first = wi.land_meeting(self.meeting, self.ctx)
        second = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(first["status"], "FAILED")
        self.assertEqual(second["status"], "FAILED")
        self.assertTrue(any("index guard" in n for n in second["notes"]))
        self.assertFalse(any("clobber guard" in n for n in second["notes"]))
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_missing_scorer_degrades_gracefully(self):
        self.ctx["scorer"] = None
        self.assertIsNone(wi.garble_check("text", None))

    def _make_garbled(self):
        speakers = ["Ada Lovelace", "Bo Chen"]
        self.meeting.sentences = [(speakers[i % 2], i * 300, "Uh.") for i in range(6)]

    def _clean_asr_text(self):
        a = ("We reviewed the quarterly roadmap this morning and aligned on three "
             "priorities: finishing the payments integration workstream, tightening "
             "partner onboarding, and drafting a clearer settlement policy before the "
             "next board update. Henry will own the on-ramp vendor comparison and "
             "circulate a short memo by Friday for everyone to react to.")
        b = ("Agreed on all of that. I also want us to confirm the dispute handling "
             "flow with the vendor, run one more load test against the staging "
             "cluster, and lock the launch window so marketing can schedule the "
             "announcement. If the numbers hold we ship the developer preview and "
             "start collecting structured feedback from the first cohort.")
        return ("# Fixture Weekly Sync\n\n- Date: 2026-07-30\n---\n"
                f"**Ada Lovelace** [00:00]: {a}\n\n**Bo Chen** [02:30]: {b}\n")

    def test_auto_retranscribe_lands_recovered_mirror(self):
        self._make_garbled()
        self.meeting.duration_min = 3            # so the clean span clears tripwires
        self.ctx["auto_retranscribe"] = True
        self.ctx["root"] = self.tmp
        asr = os.path.join(self.ctx["raw_dir"],
                           "2026-07-30_fixture_weekly_sync_asr.md")

        def stub(provider_id, slug, root):
            with open(asr, "w", encoding="utf-8") as f:
                f.write(self._clean_asr_text())
            return 0, "retranscribed", ""
        self.ctx["retranscribe"] = stub

        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "LANDED", rec["notes"])
        self.assertTrue(rec["recovered"])
        # the engine's recovered mirror is used; the original garble is never mirrored
        self.assertTrue(os.path.isfile(asr))
        self.assertFalse(os.path.isfile(os.path.join(
            self.ctx["raw_dir"], "2026-07-30_fixture_weekly_sync.md")))
        page = os.path.join(self.ctx["sources_dir"],
                            "2026-07-30_fixture_weekly_sync.md")
        with open(page, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("origin: raw/transcripts/2026-07-30_fixture_weekly_sync_asr.md",
                      text)
        self.assertIn("Raw mirror: `wiki/raw/transcripts/"
                      "2026-07-30_fixture_weekly_sync_asr.md`", text)
        self.assertIn("recovered:", text)
        self.assertTrue(any(r["op"] == "ingest" for r in al.read_wiki_log(self.tmp)))

    def test_auto_retranscribe_abort_falls_back_to_flag(self):
        self._make_garbled()
        self.ctx["auto_retranscribe"] = True
        self.ctx["root"] = self.tmp
        self.ctx["retranscribe"] = lambda pid, slug, root: (1, "", "over cap")
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FLAGGED")
        self.assertIn("auto-retranscribe failed or over cap", " ".join(rec["notes"]))
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))
        self.assertEqual(al.read_wiki_sources(self.tmp), [])

    def test_dry_run_defers_auto_retranscribe_without_spending(self):
        self._make_garbled()
        self.ctx["auto_retranscribe"] = True
        self.ctx["dry_run"] = True
        self.ctx["root"] = self.tmp
        called = []
        self.ctx["retranscribe"] = lambda pid, slug, root: called.append(1) or (0, "", "")
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FLAGGED")
        self.assertEqual(called, [])          # never spends on a dry run
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_reprocess_relands_a_garble_ledger_line_and_replaces_it(self):
        slug = "2026-07-30_fixture_weekly_sync"
        al.append_wiki_source(self.tmp, month="2026-07", slug=slug,
                              raw=f"{slug} | ledger | Garbled capture: something")
        self.ctx["index_slugs"].add(slug)
        self.ctx["reprocess"] = True
        self.ctx["reprocess_eligible"] = {slug}
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "LANDED", rec["notes"])
        # the fresh row is appended; read_index_slugs dedups to it as current state
        rows = [r for r in al.read_wiki_sources(self.tmp) if r["slug"] == slug]
        self.assertNotIn("Garbled capture", rows[-1]["raw"])
        self.assertIn(f"[[{slug}]]", rows[-1]["raw"])
        full, _series, candidates = wi.read_index_slugs(self.tmp)
        self.assertIn(slug, full)
        self.assertNotIn(slug, candidates)

    def test_reprocess_still_skips_a_non_eligible_indexed_slug(self):
        slug = "2026-07-30_fixture_weekly_sync"
        self.ctx["index_slugs"].add(slug)
        self.ctx["reprocess"] = True
        self.ctx["reprocess_eligible"] = set()      # e.g. a silent ledger line
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "SKIPPED")
        self.assertFalse(os.listdir(self.ctx["raw_dir"]))

    def test_existing_source_page_fails_rather_than_overwrites(self):
        page = os.path.join(self.ctx["sources_dir"], "2026-07-30_fixture_weekly_sync.md")
        with open(page, "w", encoding="utf-8") as f:
            f.write("existing page")
        rec = wi.land_meeting(self.meeting, self.ctx)
        self.assertEqual(rec["status"], "FAILED")
        with open(page, encoding="utf-8") as f:
            self.assertEqual(f.read(), "existing page")


if __name__ == "__main__":
    unittest.main()
