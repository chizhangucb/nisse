#!/usr/bin/env python3
"""Re-transcribe a garbled meeting capture through AssemblyAI (tier 2).

Takes a LOCAL audio file (export it from your capture tool), transcribes it
with speaker labels, and writes a verbatim mirror to
wiki/raw/transcripts/<slug>_asr.md BESIDE the untouched original, never over
it. Verify-or-abort: the new transcript's garble score
(scripts/transcript_quality_score.py) must beat the original's, else nothing
is written and the failure is reported visibly. A cost estimate is checked
against the cap BEFORE any spend; over-cap refuses.

Needs ASSEMBLYAI_API_KEY (env, then ~/.secrets/shared.env, then repo .env).
Nothing else in the starter kit needs a key.

API shapes (verify against assemblyai.com/docs if this script ever 4xx's;
observed 2026-08): POST /v2/upload (raw bytes) -> upload_url;
POST /v2/transcript {audio_url, speaker_labels: true} -> id;
GET /v2/transcript/<id> polls status queued/processing/completed/error;
completed payload carries utterances[{speaker, start(ms), text}] and
audio_duration (seconds).

Usage:
  python3 scripts/wiki_retranscribe.py --audio <file> --slug <slug>
      [--expect zh] [--cap-usd 0.50] [--dry-run]
"""
import argparse
import json
import os
import sys
import time
import urllib.request

import transcript_quality_score as tqs

API = "https://api.assemblyai.com/v2"
# Rough per-hour price used only for the pre-spend cap estimate; check
# assemblyai.com/pricing when you wire this and adjust.
PRICE_PER_HOUR_USD = 0.37
DEFAULT_CAP_USD = 0.50
POLL_S = 5
POLL_TIMEOUT_S = 1800
# Rough audio bitrate (bytes/sec) to estimate duration from file size for the
# pre-upload cap check; conservative for m4a/mp3 exports.
EST_BYTES_PER_SEC = 16000


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_key():
    """ASSEMBLYAI_API_KEY: env, then ~/.secrets/shared.env, then repo .env."""
    key = os.environ.get("ASSEMBLYAI_API_KEY")
    if key:
        return key
    for path in (os.path.expanduser("~/.secrets/shared.env"),
                 os.path.join(repo_root(), ".env")):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ASSEMBLYAI_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("\"'")
                        if val:
                            return val
        except OSError:
            continue
    return None


def _request(url, key, data=None, headers=None, raw=False):
    h = {"authorization": key}
    h.update(headers or {})
    body = data if raw else (json.dumps(data).encode() if data else None)
    if not raw and data is not None:
        h["content-type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def upload(path, key):
    with open(path, "rb") as f:
        audio = f.read()
    return _request(f"{API}/upload", key, data=audio, raw=True,
                    headers={"content-type": "application/octet-stream"}
                    )["upload_url"]


def transcribe(upload_url, key):
    job = _request(f"{API}/transcript", key,
                   data={"audio_url": upload_url, "speaker_labels": True,
                         "language_detection": True})
    tid = job["id"]
    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        got = _request(f"{API}/transcript/{tid}", key)
        if got.get("status") == "completed":
            return got
        if got.get("status") == "error":
            raise RuntimeError(f"AssemblyAI error: {got.get('error')}")
        time.sleep(POLL_S)
    raise RuntimeError("transcription timed out")


def render_mirror(slug, result):
    """The verbatim mirror in the house turn format the scorer parses.
    Labels stay `Speaker N`: attribution is a claim and belongs on the source
    page, never in the raw mirror."""
    lines = [f"# {slug} (ASR re-transcription)",
             "",
             "Engine: AssemblyAI, speaker labels machine-assigned "
             "(Speaker N, never resolved names). Recovered mirror; the "
             "original stays untouched beside it.",
             "",
             "---",
             ""]
    for u in result.get("utterances") or []:
        secs = int(u.get("start", 0)) // 1000
        stamp = f"[{secs // 60:02d}:{secs % 60:02d}]"
        lines.append(f"**Speaker {u.get('speaker', '?')}** {stamp}: "
                     f"{(u.get('text') or '').strip()}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True, help="local audio file")
    ap.add_argument("--slug", required=True,
                    help="series slug; mirror lands as <slug>_asr.md")
    ap.add_argument("--expect", default=None,
                    help="expected language code for the scorer (e.g. zh)")
    ap.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    root = repo_root()
    audio = os.path.expanduser(args.audio)
    if not os.path.exists(audio):
        print(f"retranscribe: audio not found: {audio}", file=sys.stderr)
        return 2
    original = os.path.join(root, "wiki", "raw", "transcripts",
                            f"{args.slug}.md")
    target = os.path.join(root, "wiki", "raw", "transcripts",
                          f"{args.slug}_asr.md")
    if os.path.exists(target):
        print(f"retranscribe: {target} already exists; refusing to overwrite "
              "a raw mirror (raw/ is immutable). Remove it deliberately "
              "first if you mean to redo.", file=sys.stderr)
        return 2

    est_hours = os.path.getsize(audio) / EST_BYTES_PER_SEC / 3600
    est_usd = est_hours * PRICE_PER_HOUR_USD
    print(f"plan: {audio} (~{est_hours * 60:.0f} min audio, est "
          f"${est_usd:.2f} vs cap ${args.cap_usd:.2f}) -> {target}")
    if est_usd > args.cap_usd:
        print("retranscribe: estimate exceeds the cap; refusing before any "
              "spend. Raise --cap-usd deliberately if this meeting is worth "
              "it.", file=sys.stderr)
        return 3
    if args.dry_run:
        print("dry-run: nothing uploaded, nothing written.")
        return 0

    key = load_key()
    if not key:
        print("retranscribe: no ASSEMBLYAI_API_KEY (env, "
              "~/.secrets/shared.env, or .env). This is a tier-2 connector; "
              "see .env.example.", file=sys.stderr)
        return 2

    print("uploading + transcribing (polls every 5s)...")
    result = transcribe(upload(audio, key), key)
    mirror = render_mirror(args.slug, result)

    new_score = tqs.score(mirror, expect=args.expect)
    old_score = None
    if os.path.exists(original):
        with open(original, encoding="utf-8") as f:
            old_score = tqs.score(f.read(), expect=args.expect)

    print(f"score: new={new_score['verdict']} "
          f"(wpm {new_score['words_per_min']}, turns {new_score['turns']})"
          + (f", original={old_score['verdict']}" if old_score else ""))
    # Verify-or-abort: a re-transcription that is itself garbled, or no better
    # than a non-garbled original, does not land.
    if new_score["garbled"]:
        print("retranscription FAILED: the new transcript still scores "
              "garbled. Nothing written.", file=sys.stderr)
        return 4
    if old_score and not old_score["garbled"]:
        print("original already scores OK; landing the ASR mirror anyway "
              "would add nothing. Nothing written.", file=sys.stderr)
        return 4

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(mirror)
    dur = result.get("audio_duration")
    print(f"landed: {os.path.relpath(target, root)}"
          + (f" ({dur}s audio)" if dur else ""))
    print("next: source page gets `recovered:` frontmatter; speaker "
          "identity goes in its Name gaps, never into the mirror "
          "(skills/wiki-retranscribe/SKILL.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
