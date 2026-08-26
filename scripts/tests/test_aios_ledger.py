"""Tests for scripts/aios_ledger.py (the sanctioned JSONL ledger writer).

Run from the repo root: python3 -m pytest scripts/tests/ (or unittest).
Each case writes into a throwaway hub in a tempdir.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import aios_ledger as al


class TestDecisions(unittest.TestCase):
    def setUp(self):
        self.hub = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.hub, "records"))

    def tearDown(self):
        shutil.rmtree(self.hub, ignore_errors=True)

    def _append(self, **kw):
        base = dict(date="2026-01-06", title="A decision",
                    session="s-1", stream="projects",
                    body="- **Do the thing.** because. -> x")
        base.update(kw)
        return al.append_decision(self.hub, **base)

    def test_append_and_read(self):
        ok, reason = self._append()
        self.assertTrue(ok, reason)
        rows = al.read_decisions(self.hub)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "A decision")

    def test_idempotent_per_session_stream(self):
        self.assertTrue(self._append()[0])
        ok, reason = self._append(title="Same session and stream")
        self.assertFalse(ok)
        self.assertIn("already exists", reason)
        # a different stream for the same session is allowed
        self.assertTrue(self._append(stream="ops")[0])
        self.assertEqual(len(al.read_decisions(self.hub)), 2)

    def test_em_dash_refused(self):
        ok, reason = self._append(body="- **No.** an em dash \u2014 here.")
        self.assertFalse(ok)
        self.assertIn("em dash", reason)

    def test_bad_body_shape_refused(self):
        ok, _ = self._append(body="not a bullet")
        self.assertFalse(ok)


class TestSessions(unittest.TestCase):
    def setUp(self):
        self.hub = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.hub, "records"))

    def tearDown(self):
        shutil.rmtree(self.hub, ignore_errors=True)

    def test_insert_then_refresh_keeps_one_row(self):
        self.assertTrue(al.upsert_session(
            self.hub, session="s-9", stamp="2026-01-06 0900", repo="hub"))
        # refresh: same session, later stamp, no focus -> keeps (pending)
        self.assertTrue(al.upsert_session(
            self.hub, session="s-9", stamp="2026-01-06 1000", repo="hub"))
        rows = al.read_sessions(self.hub)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stamp"], "2026-01-06 1000")
        self.assertEqual(rows[0]["focus"], "(pending)")

    def test_set_focus_fills_pending(self):
        al.upsert_session(self.hub, session="s-9", stamp="2026-01-06 0900",
                          repo="hub")
        self.assertTrue(al.set_focus(self.hub, "s-9", "ship the ledger"))
        self.assertEqual(al.read_sessions(self.hub)[0]["focus"],
                         "ship the ledger")

    def test_stored_oldest_first(self):
        al.upsert_session(self.hub, session="a", stamp="2026-01-06 0900",
                          repo="hub")
        al.upsert_session(self.hub, session="b", stamp="2026-01-06 1000",
                          repo="hub")
        # file order is oldest-first; read_sessions returns newest-first
        raw = al.read_rows(os.path.join(self.hub, "records", "sessions.jsonl"))
        self.assertEqual([r["session"] for r in raw], ["a", "b"])
        self.assertEqual(
            [r["session"] for r in al.read_sessions(self.hub)], ["b", "a"])


class TestTolerantReader(unittest.TestCase):
    def test_skips_a_bad_line(self):
        hub = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, hub, True)
        os.makedirs(os.path.join(hub, "records"))
        path = os.path.join(hub, "records", "decisions.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"date": "2026-01-06", "title": "ok", "session": "s", '
                    '"stream": "p", "body": "- **x.** y."}\n')
            f.write("this is a torn / hand-edited line\n")
        self.assertEqual(len(al.read_decisions(hub)), 1)


if __name__ == "__main__":
    unittest.main()
