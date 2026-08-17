"""Tests for scripts/transcript_quality_score.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import transcript_quality_score as tqs


def turns(pairs):
    body = "\n".join(f"**Speaker A** [{m:02d}:00]: {text}"
                     for m, text in pairs)
    return f"# header\n\n---\n\n{body}\n"


class TestScore(unittest.TestCase):
    def test_clean_transcript_ok(self):
        # 5 turns, ~150 distinct words each, over 4 minutes: ~190 wpm, no loop
        text = turns([(i, " ".join(f"point{i}{j} detail" for j in range(75)))
                      for i in range(0, 5)])
        r = tqs.score(text)
        self.assertEqual(r["verdict"], "OK")
        self.assertFalse(r["garbled"])

    def test_low_rate_garble(self):
        # 3 words across 60 minutes: implausible speech rate
        text = turns([(0, "hello"), (30, "yes"), (60, "okay")])
        r = tqs.score(text)
        self.assertTrue(r["low_rate"])
        self.assertEqual(r["verdict"], "GARBLED")

    def test_loop_garble(self):
        text = turns([(i, "the same phrase again " * 10) for i in range(5)])
        r = tqs.score(text)
        self.assertTrue(r["looped"])
        self.assertTrue(r["garbled"])

    def test_collapsed_timestamps_flagged_not_cleared(self):
        text = turns([(0, "words " * 50), (0, "words " * 50)])
        r = tqs.score(text)
        self.assertTrue(r["timestamps_broken"])
        # broken denominator must never produce a trusted low_rate verdict
        self.assertFalse(r["low_rate"])

    def test_zh_mismatch(self):
        text = turns([(i, "english only output " * 5) for i in range(0, 30)])
        r = tqs.score(text, expect="zh")
        self.assertTrue(r["lang_mismatch"])
        self.assertTrue(r["garbled"])

    def test_no_turns_is_not_garbled(self):
        r = tqs.score("# just a header\n\n---\n\nprose without turn lines\n")
        self.assertEqual(r["turns"], 0)
        self.assertFalse(r["garbled"])


if __name__ == "__main__":
    unittest.main()
