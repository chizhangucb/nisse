"""Tests for scripts/wiki_retranscribe.py gates (no network)."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wiki_retranscribe as wr


class TestGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.audio = os.path.join(self.tmp.name, "meeting.m4a")
        with open(self.audio, "wb") as f:
            f.write(b"0" * 1024)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dry_run_never_spends(self):
        rc = wr.main(["--audio", self.audio, "--slug", "x", "--dry-run"])
        self.assertEqual(rc, 0)  # no key needed, nothing written

    def test_cap_refuses_before_spend(self):
        # ~350MB estimates hours of audio, blowing the default $0.50 cap
        with open(self.audio, "wb") as f:
            f.seek(350 * 1024 * 1024 - 1)
            f.write(b"0")
        rc = wr.main(["--audio", self.audio, "--slug", "x"])
        self.assertEqual(rc, 3)

    def test_missing_audio(self):
        rc = wr.main(["--audio", "/nope/missing.m4a", "--slug", "x"])
        self.assertEqual(rc, 2)

    def test_render_mirror_shape(self):
        mirror = wr.render_mirror("slug", {"utterances": [
            {"speaker": "A", "start": 65000, "text": "hello there"}]})
        self.assertIn("**Speaker A** [01:05]: hello there", mirror)
        self.assertIn("---", mirror)  # scorer body separator

    def test_refuses_overwrite_of_existing_mirror(self):
        target = os.path.join(wr.repo_root(), "wiki", "raw", "transcripts",
                              "zz_test_slug_asr.md")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write("existing raw mirror\n")
        try:
            rc = wr.main(["--audio", self.audio, "--slug", "zz_test_slug"])
            self.assertEqual(rc, 2)
            with open(target) as f:
                self.assertEqual(f.read(), "existing raw mirror\n")
        finally:
            os.remove(target)


if __name__ == "__main__":
    unittest.main()
