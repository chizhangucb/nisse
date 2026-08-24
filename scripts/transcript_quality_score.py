#!/usr/bin/env python3
"""Garble detector for meeting transcripts.

Scores a mirrored transcript for the failure modes that make a capture
untrustworthy, deterministically and read-only. Callers: the wiki ingest pass
(gate a fresh capture) and scripts/wiki_retranscribe.py (gate the original,
verify the re-transcription).

Language-neutral signals, stdlib only, no model, no cost:
1. words/min floor: conversationally implausible speech rate (cross-language
   ASR failures run 3-13 wpm; normal speech runs 120-150).
2. denominator guard: collapsed or identical timestamps make the wpm blow up;
   when the turn span is implausibly small the wpm is untrustworthy, flagged,
   and never used to clear a transcript.
3. repeated-n-gram loop: ASR failure's universal signature is a phrase
   repeated on a loop. Detected on character n-grams, so it catches any
   language.
4. language mismatch vs an expected profile: when the meeting's expected
   language is known (e.g. `--expect zh`), a transcript whose dominant script
   is not that language is suspect.

Turn format expected in the body (after the first standalone `---`):
    **Speaker** [MM:SS]: text      (or [HH:MM:SS])

Usage:
    python3 scripts/transcript_quality_score.py <transcript.md> [--expect zh]
                                                [--json]

Exit code 0 always; the verdict is in stdout (human) or --json (machine).
"""

import json
import re
import sys

# CJK Unified Ideographs (+ common extension A). Enough to count Han reliably.
_HAN = re.compile(r"[㐀-䶿一-鿿]")
_LATIN = re.compile(r"[A-Za-z]")
_TURN = re.compile(r"^\*\*(.+?)\*\*\s*\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]:\s*(.*)$")
_EN_WORD = re.compile(r"[A-Za-z]+")

# Below this words/min a capture is conversationally implausible.
GARBLE_WPM_CEILING = 30
# A recovered Chinese meeting carries far more than this; a garble carries ~0.
HAN_FLOOR = 20
# With two or more turns, a span this small means collapsed/identical
# timestamps, not a real meeting: the wpm derived from it is untrustworthy.
MIN_SPAN_MIN = 0.1
# Loop detection: an ASR loop is high repetition over a SMALL vocabulary, so it
# takes both signals. Repeat ratio = 1 - unique/total n-grams (a loop repeats,
# so this climbs). Distinct floor = the count of distinct n-grams below which
# the vocabulary is loop-tiny; a long unique passage repeated verbatim has a
# high repeat ratio but a large vocabulary, so it is not a loop.
LOOP_NGRAM = 10
LOOP_REPEAT_CEILING = 0.5
LOOP_DISTINCT_FLOOR = 120
# Below this many characters, the repeat ratio is too noisy to judge a loop.
LOOP_MIN_CHARS = 120

# Domain terms a good non-English pass keeps in English rather than
# transliterating. Reported as a labeled quality bonus, never a pass/fail
# gate; replace with your own recurring vocabulary.
_EN_TERMS = ["API", "agent", "integration", "roadmap", "deploy"]


def parse_body(text):
    """Return the transcript body (turns after the first standalone '---')."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[i + 1:])
    return text  # no separator: score the whole thing


def _loop_stats(text, n=LOOP_NGRAM):
    """Return (repeat_ratio, distinct_ngrams) over character n-grams. Repeat
    ratio is 1 - unique/total (climbs when a phrase repeats); distinct is the
    vocabulary size (tiny for a real ASR loop, large for a long unique passage
    repeated). Language-neutral: it runs on characters, not words."""
    compact = re.sub(r"\s+", "", text)
    if len(compact) < LOOP_MIN_CHARS:
        return 0.0, 0
    grams = [compact[i:i + n] for i in range(len(compact) - n + 1)]
    if not grams:
        return 0.0, 0
    distinct = len(set(grams))
    return 1.0 - distinct / len(grams), distinct


def score(text, expect=None):
    """Score a transcript. `expect` is an optional language code ('zh') naming
    the meeting's expected language for the mismatch signal."""
    body = parse_body(text)
    han = len(_HAN.findall(body))
    turns = []
    for line in body.splitlines():
        m = _TURN.match(line.strip())
        if not m:
            continue
        _speaker, g1, g2, g3, content = m.groups()
        if g3 is not None:  # [HH:MM:SS]
            secs = int(g1) * 3600 + int(g2) * 60 + int(g3)
        else:  # [MM:SS]
            secs = int(g1) * 60 + int(g2)
        turns.append((secs, content))

    en_words = sum(len(_EN_WORD.findall(c)) for _, c in turns)
    content = " ".join(c for _, c in turns)
    latin = len(_LATIN.findall(content))

    raw_span = (turns[-1][0] - turns[0][0]) / 60.0 if turns else 0.0
    # Denominator guard: two or more turns crammed into ~no time means the
    # timestamps collapsed; the wpm is meaningless and must not clear a capture.
    timestamps_broken = len(turns) >= 2 and raw_span < MIN_SPAN_MIN
    wpm = ((han + en_words) / raw_span) if raw_span > 0 else 0.0

    loop_repeat, loop_distinct = _loop_stats(content)
    looped = (loop_repeat >= LOOP_REPEAT_CEILING
              and 0 < loop_distinct <= LOOP_DISTINCT_FLOOR
              and len(turns) > 0)

    # Implausibly slow speech, only trusted when there is a real measured span:
    # a zero or collapsed span means the rate is unknown, not slow.
    low_rate = (len(turns) > 0 and not timestamps_broken and raw_span > 0
                and wpm < GARBLE_WPM_CEILING)

    # Language mismatch vs an expected profile. The Chinese Han-floor is the
    # concrete case: a meeting expected in Chinese that returned almost no Han
    # characters and mostly Latin is the English-ASR-on-Mandarin failure.
    lang_mismatch = False
    if expect == "zh" and len(turns) > 0:
        lang_mismatch = han < HAN_FLOOR and latin > han

    garbled = bool(looped or low_rate or lang_mismatch)
    terms_kept = [t for t in _EN_TERMS if re.search(re.escape(t), body)]

    return {
        "turns": len(turns),
        "han": han,
        "english_words": en_words,
        "duration_min": round(raw_span, 1),
        "words_per_min": round(wpm, 1),
        "timestamps_broken": timestamps_broken,
        "loop_repeat": round(loop_repeat, 3),
        "loop_distinct": loop_distinct,
        "looped": looped,
        "low_rate": low_rate,
        "lang_mismatch": lang_mismatch,
        "english_terms_preserved": terms_kept,
        "garbled": garbled,
        "verdict": "GARBLED" if garbled else "OK",
    }


def _reason(r):
    reasons = []
    if r["looped"]:
        reasons.append(f"repeated-n-gram loop (repeat {r['loop_repeat']})")
    if r["low_rate"]:
        reasons.append(f"implausible {r['words_per_min']} wpm")
    if r["lang_mismatch"]:
        reasons.append("dominant script is not the expected language")
    return "; ".join(reasons)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    expect = None
    for i, a in enumerate(sys.argv):
        if a == "--expect" and i + 1 < len(sys.argv):
            expect = sys.argv[i + 1]
    if not args:
        print("usage: transcript_quality_score.py <transcript.md> "
              "[--expect zh] [--json]", file=sys.stderr)
        sys.exit(0)
    with open(args[0], encoding="utf-8") as f:
        result = score(f.read(), expect=expect)
    result["file"] = args[0]
    if as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{result['verdict']:8} {args[0]}")
        print(f"  turns={result['turns']} han={result['han']} "
              f"en_words={result['english_words']} "
              f"dur={result['duration_min']}min wpm={result['words_per_min']}"
              + (" [timestamps broken]" if result["timestamps_broken"] else ""))
        if result["garbled"]:
            print(f"  -> {_reason(result)}: retranscribe.")


if __name__ == "__main__":
    main()
