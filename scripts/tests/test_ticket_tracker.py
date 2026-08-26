"""Tests for scripts/ticket_tracker.py. All offline: the tracker client is a
fake with canned payloads, git/sessions/decisions are strings, files are a
set. No network anywhere.

Uses the default TICKET_TRACKER_KEY_PREFIX ("PROJ") since these tests don't
set that env var; issue identifiers below are "PROJ-N" to match.
"""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ticket_tracker as tt


def issue(identifier, state_name, state_type, description="", updated="2026-08-01",
          children=(), title=None, comments=(), history=()):
    return {
        "id": f"uuid-{identifier}",
        "identifier": identifier,
        "title": title or f"title {identifier}",
        "description": description,
        "updatedAt": updated + "T00:00:00.000Z",
        "state": {"name": state_name, "type": state_type},
        "children": [{"identifier": c[0],
                      "state": {"name": c[1], "type": c[2]}} for c in children],
        "comments": list(comments),
        "history": list(history),
    }


TODAY = date(2026, 8, 8)


def run(issues, git_recent="", git_window="", sessions_recent="",
        decision_dates=None, existing_files=frozenset()):
    return tt.run_checks(
        issues,
        git_window_text=git_window,
        recent_activity_text=git_recent + "\n" + sessions_recent,
        decision_dates=decision_dates,   # {ident: date} from decisions.jsonl
        file_exists=lambda p: p in existing_files,
        today=TODAY,
    )


class CheckA(unittest.TestCase):
    def test_commit_ref_to_todo_proposes_start(self):
        r = run([issue("PROJ-1", "Todo", "unstarted")],
                git_window="PROJ-1: built the thing")
        self.assertEqual(r.fixes, [{"issue": "PROJ-1", "to": "In Progress",
                                    "reason": "commit references it"}])

    def test_mid_subject_mention_is_not_evidence(self):
        r = run([issue("PROJ-1", "Backlog", "backlog")],
                git_window="records: decision blocks for PROJ-1")
        self.assertEqual(r.fixes, [])


class CheckB(unittest.TestCase):
    def test_in_review_with_unstarted_child_reopens(self):
        r = run([issue("PROJ-2", "In Review", "started",
                       children=[("PROJ-3", "Todo", "unstarted")])])
        self.assertEqual(r.fixes, [{"issue": "PROJ-2", "to": "In Progress",
                                    "reason": "In Review with unstarted children"}])


class CheckC(unittest.TestCase):
    def test_stale_in_progress_flagged(self):
        r = run([issue("PROJ-4", "In Progress", "started")])
        self.assertTrue(any("stale" in f.message for f in r.findings))

    def test_recent_touch_clears_stale(self):
        r = run([issue("PROJ-4", "In Progress", "started")],
                git_recent="PROJ-4: still going")
        self.assertFalse(any("stale" in f.message for f in r.findings))


class CheckG(unittest.TestCase):
    def test_in_review_joins_signoff_queue(self):
        r = run([issue("PROJ-5", "In Review", "started")])
        self.assertEqual(r.signoff_queue, ["PROJ-5"])

    def test_backpressure_cap(self):
        issues = [issue(f"PROJ-{n}", "In Review", "started")
                  for n in range(10, 10 + tt.BACKPRESSURE_CAP + 1)]
        r = run(issues)
        self.assertTrue(any("backpressure" in f.message for f in r.findings))


class OwnerCommentCheck(unittest.TestCase):
    def test_dormant_without_owner_email(self):
        # TICKET_TRACKER_OWNER_EMAIL unset in the test env: this check must
        # never fire, regardless of comment content.
        self.assertEqual(tt.OWNER_EMAIL, "")
        node = issue("PROJ-6", "Todo", "unstarted",
                     comments=[{"body": "any", "createdAt": "2026-08-01T00:00:00Z",
                               "user": {"email": "someone@example.com"},
                               "botActor": None,
                               "isArtificialAgentSessionRoot": False}])
        self.assertIsNone(tt._unaddressed_owner_comment(node))


class FakeClient:
    def __init__(self, issues):
        self.issues = issues
        self.set_calls = []

    def fetch_issues(self, project):
        return self.issues

    def set_state(self, issue_identifier, state_name):
        self.set_calls.append((issue_identifier, state_name))
        return True


class SweepTest(unittest.TestCase):
    def test_clean_board_pings_nothing(self, ):
        import tempfile
        client = FakeClient([issue("PROJ-7", "Done", "completed")])
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            result = tt.sweep(client, ["ExampleBoard"], state_path,
                              git_window_text="", recent_activity_text="",
                              decision_dates=None, file_exists=lambda p: False,
                              today=TODAY)
        self.assertIsNone(result["ping"])
        self.assertEqual(result["fixed"], 0)

    def test_autofix_applied_and_pinged(self):
        import tempfile
        client = FakeClient([issue("PROJ-8", "Todo", "unstarted")])
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "state.json")
            result = tt.sweep(client, ["ExampleBoard"], state_path,
                              git_window_text="PROJ-8: start",
                              recent_activity_text="", decision_dates=None,
                              file_exists=lambda p: False, today=TODAY)
        self.assertEqual(result["fixed"], 1)
        self.assertIn(("PROJ-8", "In Progress"), client.set_calls)
        self.assertIn("PROJ-8", result["ping"])


class RollupTest(unittest.TestCase):
    def test_empty_board_all_clear(self):
        text = tt.build_rollup([], set(), set(), TODAY)
        self.assertIn("all clear", text)

    def test_review_bucket_listed(self):
        text = tt.build_rollup([issue("PROJ-9", "In Review", "started")],
                               set(), set(), TODAY)
        self.assertIn("PROJ-9", text)


class DryRunClientTest(unittest.TestCase):
    def test_set_state_never_mutates(self):
        inner = FakeClient([])
        dry = tt.DryRunClient(inner)
        ok = dry.set_state("PROJ-1", "In Progress")
        self.assertTrue(ok)
        self.assertEqual(inner.set_calls, [])
        self.assertEqual(dry.would_fix, [{"issue": "PROJ-1", "to": "In Progress"}])


class ConfigTest(unittest.TestCase):
    def test_missing_key_raises_config_error(self):
        with self.assertRaises(tt.ConfigError):
            tt.LinearClient("")


if __name__ == "__main__":
    unittest.main()
