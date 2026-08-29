"""Tests for scripts/emit_daily_digest.py. All offline: the emitter writes
into a TEMP hub dir (AIOS_HUB or the explicit --hub/hub= override), never the
real hub spool."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import emit_daily_digest as edd

REQUIRED_KEYS = {"repo", "date", "needs_you", "auto_done", "health"}


class TestEmit(unittest.TestCase):
    def test_writes_valid_artifact_to_temp_hub(self):
        with tempfile.TemporaryDirectory() as hub_tmp, \
                tempfile.TemporaryDirectory() as repo_tmp:
            path = edd.emit(repo_tmp, hub=hub_tmp)

            expected_dir = os.path.join(hub_tmp, "records", "spool", "nisse")
            self.assertEqual(os.path.dirname(path), expected_dir)
            self.assertTrue(os.path.isfile(path))

            with open(path, encoding="utf-8") as f:
                payload = json.load(f)

            self.assertEqual(set(payload.keys()), REQUIRED_KEYS)
            self.assertEqual(payload["repo"], "nisse")
            self.assertIsInstance(payload["date"], str)
            self.assertIsInstance(payload["needs_you"], list)
            self.assertIsInstance(payload["auto_done"], dict)
            for v in payload["auto_done"].values():
                self.assertIsInstance(v, int)
            self.assertIsInstance(payload["health"], list)
            self.assertGreaterEqual(len(payload["health"]), 1)
            for line in payload["health"]:
                self.assertIsInstance(line, str)

    def test_never_touches_real_hub_spool(self):
        real_hub = edd.resolve_hub()
        real_spool = os.path.join(real_hub, "records", "spool", "nisse")
        before = set(os.listdir(real_spool)) if os.path.isdir(real_spool) else set()

        with tempfile.TemporaryDirectory() as hub_tmp, \
                tempfile.TemporaryDirectory() as repo_tmp:
            edd.emit(repo_tmp, hub=hub_tmp)

        after = set(os.listdir(real_spool)) if os.path.isdir(real_spool) else set()
        self.assertEqual(before, after)

    def test_resolve_hub_uses_aios_hub_env(self):
        with tempfile.TemporaryDirectory() as hub_tmp:
            with mock.patch.dict(os.environ, {"AIOS_HUB": hub_tmp}):
                self.assertEqual(edd.resolve_hub(), hub_tmp)

    def test_resolve_hub_falls_back_to_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AIOS_HUB", None)
            self.assertEqual(edd.resolve_hub(), os.path.expanduser("~/chizhang-2"))

    def test_git_signals_degrade_gracefully_off_repo(self):
        with tempfile.TemporaryDirectory() as not_a_repo:
            sig = edd.git_signals(not_a_repo)
            self.assertIsNone(sig["branch"])
            self.assertEqual(sig["uncommitted"], 0)
            self.assertEqual(sig["commits_24h"], 0)
            self.assertIsNone(sig["unpushed"])

    def test_build_payload_always_has_health(self):
        with tempfile.TemporaryDirectory() as not_a_repo:
            needs_you, auto_done, health = edd.build_payload(not_a_repo)
            self.assertEqual(needs_you, [])
            self.assertIn("commits", auto_done)
            self.assertGreaterEqual(len(health), 1)

    def test_atomic_write_no_leftover_tmp(self):
        with tempfile.TemporaryDirectory() as hub_tmp, \
                tempfile.TemporaryDirectory() as repo_tmp:
            path = edd.emit(repo_tmp, hub=hub_tmp)
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_main_writes_and_prints_path(self):
        with tempfile.TemporaryDirectory() as hub_tmp, \
                tempfile.TemporaryDirectory() as repo_tmp:
            rc = edd.main(["--root", repo_tmp, "--hub", hub_tmp])
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
