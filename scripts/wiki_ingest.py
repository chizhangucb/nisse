#!/usr/bin/env python3
"""Mechanical half of wiki-ingest: acquire meetings, mirror them, scaffold pages.

One entry point, one landing pipeline, one mechanical source adapter behind a
common shape (NormalizedMeeting). A future source adds an adapter function; the
pipeline never forks.

    fetch_fireflies(since, until) -> [NormalizedMeeting] -> land_meeting()

A capture tool with no public REST API (a voice recorder reached over MCP, say)
has no adapter here: the skill acquires it and lands it through this script's
scaffold path, which is the same pipeline.

The pipeline does only what is mechanical: dedupe, the already-ingested guard,
the garble gate, the raw mirror (clobber-guarded), a source-page scaffold, the
monthly index line, the log line. Everything that needs judgment (Rule 7
confidential routing, signal extraction, an unclear series slug) is emitted as
a NEEDS-JUDGMENT line for the wiki-ingest skill to resolve. This script never
guesses those.

Usage:
    python3 scripts/wiki_ingest.py --since 2026-07-24 --until 2026-07-31 --diff-only
    python3 scripts/wiki_ingest.py --since 2026-07-27 --until 2026-07-28 --dry-run
    python3 scripts/wiki_ingest.py --since 2026-07-27 --until 2026-07-28 --write-scaffold
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import wiki_ledger  # the one sanctioned wiki log/sources append path

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW_DIR = os.path.join(REPO, "wiki", "raw", "transcripts")
SOURCES_DIR = os.path.join(REPO, "wiki", "sources")
META_DIR = os.path.join(REPO, "wiki", "metadata")
INDEX_FILE = os.path.join(META_DIR, "index.md")
INDEX_SHARD_DIR = os.path.join(META_DIR, "index")
LOG_FILE = os.path.join(META_DIR, "log.md")
TEMPLATE = os.path.join(REPO, "wiki", "_templates", "source-page-meeting.md")

GQL_URL = "https://api.fireflies.ai/graphql"
LIST_LIMIT = 50          # Fireflies caps `limit` at 50 per page; paginate with `skip`
MAX_PAGES = 20           # runaway backstop: 20 pages = 1000 meetings in one window

# A recovered (re-transcribed) mirror lands beside the original as <slug>_asr.md
# (schema re-transcription naming exception). Its presence means the capture was
# already healed, so landing reads from it and never re-scores the garble.
MIRROR_SUFFIX = "_asr"


def default_retranscribe_runner(provider_id, slug, root):
    """Run scripts/wiki_retranscribe.py for one garbled capture.

    Returns (returncode, stdout, stderr). The engine carries its own
    verify-or-abort re-score and a hard $0.50/meeting cap, so a nonzero exit
    already means "refused, over cap, or not better", never "spent blindly".
    Injected via ctx so tests never touch the network or the provider.
    """
    import subprocess
    cmd = [sys.executable, os.path.join(root, "scripts", "wiki_retranscribe.py"),
           "--id", provider_id, "--slug", slug]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


class ApiError(Exception):
    pass


class ClobberError(Exception):
    """The raw target path already exists. Never overwrite a raw mirror."""


# --------------------------------------------------------------------------- #
# Normalized shape
# --------------------------------------------------------------------------- #

@dataclass
class NormalizedMeeting:
    source: str                 # fireflies, or whatever the skill lands
    provider_id: str
    title: str
    date: str                   # YYYY-MM-DD
    duration_min: int
    attendees: list             # invited, may be empty
    speakers: list              # who actually spoke
    sentences: list             # [(speaker, start_sec or None, text)]
    provider_link: str
    extra_metadata: dict = field(default_factory=dict)

    @property
    def sentence_count(self):
        return len(self.sentences)


@dataclass
class AdapterResult:
    meetings: list = field(default_factory=list)
    flags: list = field(default_factory=list)   # [{"file"/"id", "reason"}]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def slugify(text):
    text = (text or "").lower()
    text = re.sub(r"\[[^\]]*\]", " ", text)          # drop [Placeholder] etc
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_") or "untitled"


def stamp(secs):
    """Seconds to [MM:SS], or [H:MM:SS] past an hour."""
    secs = int(secs or 0)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def merge_turns(sentences):
    """Merge consecutive same-speaker sentences into one turn each."""
    turns = []
    cur = None
    for speaker, start, text in sentences:
        text = (text or "").strip()
        if not text:
            continue
        speaker = speaker or "Unknown"
        if cur and cur[0] == speaker:
            cur[2] = cur[2] + " " + text
        else:
            if cur:
                turns.append(tuple(cur))
            cur = [speaker, start, text]
    if cur:
        turns.append(tuple(cur))
    return turns


def load_dotenv_key(name, env_path=None):
    # Delegates to the shared resolver (docs/operations.md): env -> canonical
    # store -> repo .env. env_path overrides the repo fallback when given.
    from secrets_env import get_secret
    return get_secret(name, repo_env=env_path or os.path.join(REPO, ".env"))


def in_range(date_str, since, until):
    return since <= date_str <= until


# --------------------------------------------------------------------------- #
# Adapter: Fireflies
# --------------------------------------------------------------------------- #

_Q_LIST = """
query($fromDate: DateTime, $toDate: DateTime, $limit: Int, $skip: Int) {
  transcripts(fromDate: $fromDate, toDate: $toDate, limit: $limit, skip: $skip) {
    id title dateString duration transcript_url
    speakers { name }
    meeting_attendees { displayName email }
    meeting_info { fred_joined silent_meeting }
  }
}"""

# Fallback for accounts or schema versions that reject meeting_info.
_Q_LIST_MIN = """
query($fromDate: DateTime, $toDate: DateTime, $limit: Int, $skip: Int) {
  transcripts(fromDate: $fromDate, toDate: $toDate, limit: $limit, skip: $skip) {
    id title dateString duration
    speakers { name }
    meeting_attendees { displayName email }
  }
}"""

_Q_TRANSCRIPT = """
query($id: String!) {
  transcript(id: $id) {
    id title dateString duration transcript_url
    speakers { name }
    meeting_attendees { displayName email }
    sentences { speaker_name text start_time }
  }
}"""


def gql(query, variables=None, api_key=None, url=GQL_URL, timeout=60):
    key = api_key or os.environ.get("FIREFLIES_API_KEY") or load_dotenv_key("FIREFLIES_API_KEY")
    if not key:
        raise ApiError("FIREFLIES_API_KEY not set (env or repo .env)")
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.URLError as exc:
        raise ApiError(f"Fireflies unreachable: {exc}")
    if payload.get("errors"):
        raise ApiError(json.dumps(payload["errors"]))
    return payload["data"]


def _date_of(row):
    ds = row.get("dateString") or ""
    return ds[:10]


def normalize_fireflies(row, sentences=None):
    attendees = []
    for a in row.get("meeting_attendees") or []:
        name = (a or {}).get("displayName") or (a or {}).get("email")
        if name:
            attendees.append(name)
    speakers = [s.get("name") for s in (row.get("speakers") or []) if s.get("name")]
    sents = [(s.get("speaker_name"), s.get("start_time"), s.get("text"))
             for s in (sentences or [])]
    if not speakers:
        speakers = list(dict.fromkeys(s[0] for s in sents if s[0]))
    info = row.get("meeting_info") or {}
    return NormalizedMeeting(
        source="fireflies",
        provider_id=row.get("id"),
        title=row.get("title") or "untitled",
        date=_date_of(row),
        duration_min=int(round(float(row.get("duration") or 0))),
        attendees=attendees,
        speakers=speakers,
        sentences=sents,
        provider_link=row.get("transcript_url")
        or (f"https://app.fireflies.ai/view/{row.get('id')}" if row.get("id") else ""),
        extra_metadata={"fred_joined": bool(info.get("fred_joined")),
                        "silent_meeting": bool(info.get("silent_meeting"))},
    )


def _list_transcripts(since, until, fetcher):
    """Page the Fireflies listing across the whole window, newest first.

    `limit` is capped at 50 by the API, so a wide window has to walk pages with
    `skip` or the oldest meetings fall off the first page before any date filter
    sees them. Stops when a short page (< LIST_LIMIT) proves the window is
    exhausted, or at MAX_PAGES as a runaway backstop.
    """
    query = _Q_LIST
    rows, skip = [], 0
    for _ in range(MAX_PAGES):
        variables = {"fromDate": f"{since}T00:00:00.000Z",
                     "toDate": f"{until}T23:59:59.000Z",
                     "limit": LIST_LIMIT, "skip": skip}
        try:
            page = fetcher(query, variables)["transcripts"] or []
        except ApiError as exc:
            if query is _Q_LIST and ("meeting_info" in str(exc) or "fred_joined" in str(exc)):
                query = _Q_LIST_MIN
                continue          # re-fetch this same page with the minimal query
            raise
        rows += page
        if len(page) < LIST_LIMIT:
            break
        skip += LIST_LIMIT
    return rows


def fetch_fireflies(since, until, fetcher=gql, with_sentences=True):
    """List Fireflies transcripts in a date range and normalize them.

    `fetcher` is injected so tests never touch the network.
    """
    result = AdapterResult()
    rows = _list_transcripts(since, until, fetcher)
    for row in rows:
        date = _date_of(row)
        if date and not in_range(date, since, until):
            continue
        sentences = None
        if with_sentences:
            try:
                full = fetcher(_Q_TRANSCRIPT, {"id": row.get("id")})["transcript"] or {}
            except ApiError as exc:
                result.flags.append({"id": row.get("id"),
                                     "reason": f"sentence fetch failed: {exc}"})
                continue
            sentences = full.get("sentences") or []
            for key in ("speakers", "meeting_attendees", "duration",
                        "transcript_url", "title", "dateString"):
                if full.get(key) is not None:
                    row[key] = full[key]
        result.meetings.append(normalize_fireflies(row, sentences))
    return result


# --------------------------------------------------------------------------- #
# Dedupe
# --------------------------------------------------------------------------- #

def _coverage(meeting):
    stamps = [s[1] for s in meeting.sentences if s[1] is not None]
    if not stamps:
        return None
    return (min(stamps), max(stamps))


def dedupe_captures(meetings, strict=True):
    """Collapse duplicate captures of one meeting, within a source.

    The same meeting is often captured under several attendee accounts. Winner:
    most sentences; tiebreak the capture whose metadata shows fred_joined.
    Before a loser is discarded its timestamps are checked against the winner's
    coverage; anything outside means the loser holds content the winner does
    not, which is a judgment call, not a drop.

    `strict=False` skips the coverage judgment, for listing modes that fetch no
    sentences and therefore have nothing to compare.
    """
    return _dedupe_within_source(meetings, strict)


def _dedupe_within_source(meetings, strict=True):
    groups = {}
    for m in meetings:
        groups.setdefault((m.source, m.date, slugify(m.title)), []).append(m)
    kept, flags = [], []
    for key, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        if not strict:
            group = sorted(group, key=lambda m: m.sentence_count, reverse=True)
            kept.append(group[0])
            continue
        group = sorted(group,
                       key=lambda m: (m.sentence_count,
                                      1 if m.extra_metadata.get("fred_joined") else 0),
                       reverse=True)
        winner, losers = group[0], group[1:]
        win_cov = _coverage(winner)
        for loser in losers:
            outside = []
            if win_cov is not None:
                lo, hi = win_cov
                outside = [s for s in loser.sentences
                           if s[1] is not None and (s[1] < lo or s[1] > hi)]
            if outside or win_cov is None:
                reason = ("loser capture holds turns outside the winner's time "
                          "coverage" if outside else
                          "winner capture has no timestamps to compare coverage")
                flags.append({"id": loser.provider_id,
                              "reason": f"dedupe NEEDS-JUDGMENT ({key[1]} {winner.title}): "
                                        f"{reason}; kept {winner.provider_id}, "
                                        f"held {loser.provider_id}"})
                winner.extra_metadata["dedupe_conflict"] = True
            else:
                winner.extra_metadata.setdefault("excluded_captures", []).append(
                    loser.provider_id)
        kept.append(winner)
    return kept, flags


# --------------------------------------------------------------------------- #
# Series slug
# --------------------------------------------------------------------------- #

_INDEX_SLUG = re.compile(r"^-\s+(?:\[\[)?(\d{4}-\d{2}-\d{2})_([a-z0-9_]+)")


def read_index_slugs(root=REPO):
    """Return (full slugs, dateless slug -> count, reprocess candidates).

    Reads wiki/metadata/sources.jsonl. Rows are deduped by slug keeping the
    LAST occurrence:
    an append-log carries a reprocess's fresh row after its earlier garble row,
    and the latest row is the current state.

    A reprocess candidate is a slug whose current line names a garble but is not
    marked `unrecoverable` (that one already took its automated shot). It is only
    a *candidate*: reprocess_eligible_slugs() then drops any that already landed
    a source page, which is what separates a stuck garble ledger line from an
    already-recovered source (recovered lines still say "garbled slug").
    """
    latest = {}  # slug -> raw line body (last wins)
    for row in wiki_ledger.read_wiki_sources(root):
        slug = (row.get("slug") or "").strip()
        raw = row.get("raw") or ""
        if not slug:
            m = _INDEX_SLUG.match("- " + raw)
            if not m:
                continue
            slug = f"{m.group(1)}_{m.group(2)}"
        latest[slug] = raw
    full, series, candidates = set(), {}, set()
    for slug, raw in latest.items():
        m = re.match(r"(\d{4}-\d{2}-\d{2})_([a-z0-9_]+)$", slug)
        if not m:
            continue
        full.add(slug)
        series[m.group(2)] = series.get(m.group(2), 0) + 1
        if (re.search(r"garbl", raw, re.I)
                and not re.search(r"unrecoverable", raw, re.I)):
            candidates.add(slug)
    return full, series, candidates


def reprocess_eligible_slugs(candidates, sources_dir=SOURCES_DIR):
    """Candidates with no landed source page yet, so re-ingest can rebuild them."""
    return {s for s in candidates
            if not os.path.exists(os.path.join(sources_dir, f"{s}.md"))}


def read_prior_pages(sources_dir=SOURCES_DIR):
    """[(dateless slug, frozenset of participants)] from existing source pages."""
    out = []
    if not os.path.isdir(sources_dir):
        return out
    for name in sorted(os.listdir(sources_dir)):
        if not name.endswith(".md"):
            continue
        m = re.match(r"^(\d{4}-\d{2}-\d{2})_(.+)\.md$", name)
        if not m:
            continue
        try:
            with open(os.path.join(sources_dir, name), encoding="utf-8") as f:
                text = f.read(4000)
        except OSError:
            continue
        pm = re.search(r"^participants:\s*\[(.*?)\]", text, re.M | re.S)
        people = set()
        if pm:
            people = {p.strip().strip('"').strip("'")
                      for p in pm.group(1).split(",") if p.strip()}
        out.append((m.group(2), frozenset(people)))
    return out


def resolve_series_slug(meeting, series_counts, prior_pages):
    """Mechanical series slug, or a NEEDS-JUDGMENT reason when it is ambiguous.

    Returns (slug, reason or None). Order: the slugified title if that slug is
    already a known series, then a single series shared by prior pages with the
    identical attendee set, then the slugified title as the default.
    """
    default = slugify(meeting.title)
    if series_counts.get(default):
        return default, None

    # Same letters, different word split: hiring_stand_up is hiring_standup.
    flat = default.replace("_", "")
    same_letters = [slug for slug in series_counts if slug.replace("_", "") == flat]
    if len(same_letters) == 1:
        return same_letters[0], None

    # An established series the title names in other words: "Project DecaCorn
    # Weekly" is the decacorn_weekly series, "Weekly GTM & Partnership Meeting"
    # is gtm_partnership_weekly, "David - the owner" is david_owner_sync. Match when one
    # token set contains the other and the smaller one carries real signal.
    words = set(default.split("_"))
    contained = {slug for slug, count in series_counts.items()
                 if count >= 2 and slug != default
                 and _token_subset(set(slug.split("_")), words)}
    if len(contained) == 1:
        return sorted(contained)[0], None
    if len(contained) > 1:
        return default, ("series slug ambiguous: title matches established series "
                         + ", ".join(sorted(contained)))

    roster = frozenset(meeting.speakers) or frozenset(meeting.attendees)
    if roster:
        candidates = {slug for slug, people in prior_pages
                      if people and people == roster and series_counts.get(slug, 0) >= 2}
        if len(candidates) == 1:
            return sorted(candidates)[0], None
        if len(candidates) > 1:
            return default, ("series slug ambiguous: same attendee set matches "
                             + ", ".join(sorted(candidates)))
    return default, None


def _token_subset(series_words, title_words):
    """True when either token set contains the other, on 2+ shared whole tokens.

    Whole tokens only, so decacornish never matches decacorn; two tokens
    minimum, so a one-word series slug does not swallow unrelated meetings.
    """
    smaller, larger = sorted((series_words, title_words), key=len)
    return len(smaller) >= 2 and smaller <= larger


# --------------------------------------------------------------------------- #
# Garble gate
# --------------------------------------------------------------------------- #

def load_quality_scorer(path=None):
    """Import scripts/transcript_quality_score.py by path; None if absent."""
    path = path or os.path.join(REPO, "scripts", "transcript_quality_score.py")
    if not os.path.isfile(path):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("transcript_quality_score", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


_UNSET = object()


def garble_check(mirror_text, scorer=_UNSET):
    """Return the score dict, or None when no scorer is available.

    An explicit `scorer=None` means the caller has no scorer, so the gate
    degrades to a pass rather than silently loading one.
    """
    scorer = load_quality_scorer() if scorer is _UNSET else scorer
    if scorer is None:
        return None
    try:
        return scorer.score(mirror_text)
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Raw mirror
# --------------------------------------------------------------------------- #

CAPTURED_BY = {"fireflies": "Fireflies (API ingest)"}


def render_raw_mirror(meeting):
    head = [f"# {meeting.title}", ""]
    head.append(f"- Date: {meeting.date}")
    head.append(f"- Duration: {meeting.duration_min} min")
    head.append(f"- Speakers: {', '.join(meeting.speakers) or 'unknown'}")
    if meeting.source == "fireflies":
        head.append("- Invited: " + (", ".join(meeting.attendees) or "not captured"))
    head.append("- Captured by: " + (meeting.extra_metadata.get("captured_by")
                or CAPTURED_BY.get(meeting.source, meeting.source)))
    if meeting.source == "fireflies":
        head.append(f"- Source: {meeting.provider_link or 'not captured'}")
    else:
        head.append(f"- {meeting.extra_metadata.get('id_label', 'Capture file ID')}: "
                    f"{meeting.provider_id}")
        if meeting.provider_link:
            head.append(f"- Source: {meeting.provider_link}")
    if meeting.extra_metadata.get("keep_segments"):
        head.append("- Format: verbatim words, one turn per timestamped segment "
                    "(undiarized capture), segment-start timestamp")
    elif meeting.extra_metadata.get("no_timestamps"):
        head.append("- Format: verbatim words, consecutive same-speaker sentences "
                    "merged into turns, no turn timestamps in this capture")
    else:
        head.append("- Format: verbatim words, consecutive same-speaker sentences "
                    "merged into turns, turn-start timestamp")
    excluded = meeting.extra_metadata.get("excluded_captures")
    if excluded:
        head.append("- Excluded captures: " + ", ".join(excluded))
    # `keep_segments` (undiarized timestamped captures, e.g. a recorder export
    # with speaker labels off): every segment is one Unknown-speaker
    # turn, so merge_turns would collapse them all into one turn and drop every
    # timestamp but the first (which then reads as a 1-second truncated
    # transcript to the tripwires). Keep the segments as-is instead.
    if meeting.extra_metadata.get("keep_segments"):
        turns = [(sp or "Unknown", st, (tx or "").strip())
                 for sp, st, tx in meeting.sentences if (tx or "").strip()]
    else:
        turns = merge_turns(meeting.sentences)
    body = []
    for speaker, start, text in turns:
        if start is None:
            body.append(f"**{speaker}**: {text}")
        else:
            body.append(f"**{speaker}** [{stamp(start)}]: {text}")
    return "\n".join(head) + "\n\n---\n" + "\n\n".join(body) + "\n"


def write_raw_mirror(path, text, dry_run=False):
    """Clobber guard: an existing raw file stops the write, always."""
    if os.path.exists(path):
        raise ClobberError(f"raw mirror already exists: {path}")
    if dry_run:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# --------------------------------------------------------------------------- #
# Source-page scaffold
# --------------------------------------------------------------------------- #

TODO_SECTIONS = ["# Context", "# Atmosphere", "# Summary (factual)", "# Decisions",
                 "# Action Items", "# Unresolved Points", "# Signals"]

_JUDGMENT_KEYS = {"tags", "meeting_type", "context", "confidential", "distilled"}


def render_source_scaffold(meeting, slug, template_path=TEMPLATE, today=None):
    today = today or dt.date.today().isoformat()
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    parts = template.split("---\n", 2)
    frontmatter, body = parts[1], parts[2]
    values = {
        "type": "source",
        "project": "work",
        "created": meeting.date,
        "ingested": today,
        "origin": f"raw/transcripts/{slug}.md",
        "via": meeting.source,
        "retrieval": "full",
        "storage": "verbatim",
        "class": "primary",
        "participants": "[" + ", ".join(meeting.speakers) + "]",
    }
    out_lines = []
    for line in frontmatter.splitlines():
        m = re.match(r"^([a-z_]+):(\s*)(.*)$", line)
        if m and m.group(1) in values:
            # A filled key drops the template's guidance comment; the comments
            # that remain mark exactly the keys the judgment half still owes.
            out_lines.append(f"{m.group(1)}: {values[m.group(1)]}")
        else:
            out_lines.append(line)
    body_lines = []
    for line in body.splitlines():
        body_lines.append(line)
        if line.strip() in TODO_SECTIONS:
            body_lines.append("")
            body_lines.append("<!-- TODO wiki-ingest judgment half: fill this section. -->")
    body_text = "\n".join(body_lines)
    pointer = (f"Fireflies: {meeting.provider_link}" if meeting.source == "fireflies"
               else meeting.extra_metadata.get("pointer")
               or f"no shareable URL; file ID {meeting.provider_id}")
    transcript_block = (f"- {pointer}\n- Raw mirror: `wiki/raw/transcripts/{slug}.md`\n"
                        "- Excluded captures: "
                        + (", ".join(meeting.extra_metadata.get("excluded_captures", []))
                           or "none"))
    body_text = body_text.replace("# Transcript Link\n\n-\n",
                                  f"# Transcript Link\n\n{transcript_block}\n")
    return "---\n" + "\n".join(out_lines).rstrip() + "\n---\n" + body_text


def _insert_recovered_block(scaffold, today, verdict):
    """Add the `recovered:` frontmatter block to a healed capture's scaffold.

    Subkeys match scripts/wiki_retranscribe.py (engine, date, passes, verdict),
    the schema's re-transcription frontmatter. Inserted before the frontmatter's
    closing delimiter."""
    try:
        import wiki_retranscribe as wr
        engine = wr.ENGINE_ID
    except Exception:
        engine = "assemblyai"
    block = (f"recovered:\n  engine: {engine}\n  date: {today}\n"
             f"  passes: 1\n  verdict: \"{verdict or 'auto-retranscribed at ingest'}\"\n")
    parts = scaffold.split("---\n", 2)
    if len(parts) == 3:
        return "---\n" + parts[1] + block + "---\n" + parts[2]
    return scaffold


# --------------------------------------------------------------------------- #
# Index and log appends
# --------------------------------------------------------------------------- #

SHARD_HEADER = ("# Sources: {month}\n\n"
                "Meeting sources for the month, one line per meeting, newest first.\n\n")


def shard_path(date, shard_dir=INDEX_SHARD_DIR):
    return os.path.join(shard_dir, f"sources-{date[:7]}.md")


def index_line(meeting, slug):
    return (f"- [[{slug}]] | meeting {meeting.date}, {meeting.title} | work | verbatim "
            "| TODO annotation (wiki-ingest judgment half)")


def _index_slug_re(slug):
    """Regex matching an existing ledger line for `slug` in a monthly shard."""
    return rf"^-\s+(?:\[\[)?{re.escape(slug)}\b"


def index_carries_slug(slug, root=REPO):
    """Read-only probe: does sources.jsonl already carry `slug`?

    A True here means `append_index_line(..., replace=False)` would raise
    ClobberError. Lets land_meeting run the index guard *before* the raw mirror
    is written, so a clobber never orphans a mirror.
    """
    for row in wiki_ledger.read_wiki_sources(root):
        if (row.get("slug") or "").strip() == slug:
            return True
    return False


def append_index_line(meeting, slug, root=REPO, dry_run=False, replace=False):
    """Append the source line to wiki/metadata/sources.jsonl.

    An already-present slug is a hard stop: the sources log is the ingest ledger
    and a second row for the same meeting would be a silent double ingest.
    `replace` (reprocess mode) appends a fresh row anyway; the append-log keeps
    the earlier row as history and read_index_slugs dedups by slug keeping the
    latest, so the fresh row is the current state.
    """
    line = index_line(meeting, slug)
    if index_carries_slug(slug, root) and not replace:
        raise ClobberError(f"sources.jsonl already carries {slug}")
    if not dry_run:
        ok, why = wiki_ledger.append_wiki_source(
            root, month=meeting.date[:7], slug=slug, raw=line[len("- "):])
        if not ok:
            raise ClobberError(f"sources append refused for {slug}: {why}")
    return line


def log_line(meeting, slug, today=None):
    today = today or dt.date.today().isoformat()
    return (f"- {today} | ingest | [[{slug}]] landed via {meeting.source}; "
            "scaffold pending judgment half")


def append_log_line(meeting, slug, root=REPO, dry_run=False, today=None):
    today = today or dt.date.today().isoformat()
    line = log_line(meeting, slug, today)
    if not dry_run:
        detail = (f"[[{slug}]] landed via {meeting.source}; "
                  "scaffold pending judgment half")
        wiki_ledger.append_wiki_log(root, date=today, op="ingest", detail=detail)
    return line


def count_undistilled(sources_dir=SOURCES_DIR):
    count = 0
    if not os.path.isdir(sources_dir):
        return 0
    for name in sorted(os.listdir(sources_dir)):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(sources_dir, name), encoding="utf-8") as f:
                head = f.read(3000)
        except OSError:
            continue
        m = re.search(r"^distilled:(.*)$", head, re.M)
        if m and not m.group(1).split("#")[0].strip():
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Landing pipeline
# --------------------------------------------------------------------------- #

def land_meeting(meeting, ctx):
    """Run one meeting through every stage. Returns a record dict.

    Statuses: LANDED, SKIPPED (already ingested), FLAGGED (garble or judgment),
    FAILED (clobber guard or a truncation tripwire). A FAILED or FLAGGED meeting
    never reaches the index or log, so a bad ingest never feeds distill.
    """
    rec = {"title": meeting.title, "date": meeting.date, "source": meeting.source,
           "provider_id": meeting.provider_id, "status": "LANDED", "notes": []}

    slug_body, reason = resolve_series_slug(meeting, ctx["series_counts"],
                                            ctx["prior_pages"])
    slug = f"{meeting.date}_{slug_body}"
    rec["slug"] = slug
    if reason:
        rec["status"] = "FLAGGED"
        rec["notes"].append("NEEDS-JUDGMENT: " + reason)
        return rec

    reprocessing = (ctx.get("reprocess")
                    and slug in ctx.get("reprocess_eligible", set()))
    if slug in ctx["index_slugs"] and not reprocessing:
        rec["status"] = "SKIPPED"
        rec["notes"].append("already ingested: slug present in the metadata index")
        return rec
    if reprocessing:
        rec["notes"].append("reprocess: re-ingesting a garble ledger line "
                            "(replaces the index line on success)")

    if meeting.extra_metadata.get("dedupe_conflict"):
        rec["status"] = "FLAGGED"
        rec["notes"].append("NEEDS-JUDGMENT: duplicate capture holds turns the kept "
                            "capture does not")
        return rec

    if not meeting.sentences:
        rec["status"] = "FLAGGED"
        rec["notes"].append("NEEDS-JUDGMENT: no sentences retrieved (Rule 5 gap)")
        return rec

    # A recovered mirror already present for this slug means a prior
    # retranscription healed the capture: land from it, never re-score the
    # garble, never rewrite the raw (the engine owns it).
    asr_path = os.path.join(ctx["raw_dir"], f"{slug}{MIRROR_SUFFIX}.md")
    recovered = os.path.exists(asr_path)
    recover_verdict = None
    if recovered:
        with open(asr_path, encoding="utf-8") as f:
            mirror_text = f.read()
        mirror_path = asr_path
        recover_verdict = "recovered mirror present at ingest"
    else:
        mirror_text = render_raw_mirror(meeting)
        score = garble_check(mirror_text, ctx.get("scorer"))
        if score is None:
            rec["notes"].append("garble score unavailable, gate degraded to pass")
        elif score.get("garbled"):
            if not ctx.get("auto_retranscribe"):
                rec["status"] = "FLAGGED"
                rec["notes"].append("garbled capture: flag for retranscription "
                                    "(wiki-retranscribe), garble not mirrored")
                return rec
            if ctx["dry_run"]:
                rec["status"] = "FLAGGED"
                rec["notes"].append("garbled capture: auto-retranscribe deferred "
                                    "(dry run spends nothing)")
                return rec
            # Auto-heal: the engine garble-gates, transcribes, re-scores and
            # aborts if not better, and enforces its own per-meeting cost cap.
            code, out, err = ctx["retranscribe"](meeting.provider_id, slug,
                                                 ctx["root"])
            if code != 0 or not os.path.exists(asr_path):
                rec["status"] = "FLAGGED"
                rec["notes"].append("auto-retranscribe failed or over cap; ledger "
                                    "line: " + (err or out).strip()[:200])
                return rec
            with open(asr_path, encoding="utf-8") as f:
                mirror_text = f.read()
            rescore = garble_check(mirror_text, ctx.get("scorer"))
            if rescore and rescore.get("garbled"):
                rec["status"] = "FLAGGED"
                rec["notes"].append("auto-retranscribe still garbled after "
                                    "re-score; ledger line")
                return rec
            recovered = True
            mirror_path = asr_path
            recover_verdict = (f"{rescore['verdict']} han={rescore['han']}"
                               if rescore else "auto-retranscribed at ingest")
            rec["notes"].append(f"auto-retranscribed: recovered mirror "
                                f"{slug}{MIRROR_SUFFIX}.md")
        if not recovered:
            mirror_path = os.path.join(ctx["raw_dir"], f"{slug}.md")

    # Truncation tripwire runs against the in-memory mirror text before any
    # write to raw/. A FAIL must never leave an orphaned mirror on disk with
    # no index entry: raw/ is immutable (nothing ever deletes it), so a write
    # followed by a tripwire FAIL would clobber-guard on retry forever, since
    # --diff-only only checks the index.
    checks = ctx["run_checks"](mirror_text, meeting.duration_min, meeting.speakers)
    rec["checks"] = [{"name": c.name, "status": c.status, "detail": c.detail}
                     for c in checks]
    failed = [c for c in checks if c.status == "FAIL"]
    if failed:
        rec["status"] = "FAILED"
        rec["notes"] += [f"tripwire FAIL {c.name}: {c.detail}" for c in failed]
        return rec
    rec["notes"] += [f"tripwire WARN {c.name}: {c.detail}"
                     for c in checks if c.status == "WARN"]

    # The two guards downstream share one failure shape. Each can
    # FAIL *after* the raw mirror is written, orphaning the mirror with no
    # index entry (raw/ is immutable, so a retry clobber-guards forever). Run
    # both as read-only pre-checks here, before write_raw_mirror(), so a FAIL
    # leaves nothing on disk and a later retry re-hits the same clean FAIL.
    rec["scaffold_path"] = os.path.join(ctx["sources_dir"], f"{slug}.md")
    if ctx["write_scaffold"] and os.path.exists(rec["scaffold_path"]):
        rec["status"] = "FAILED"
        rec["notes"].append("source page already exists: "
                            f"{rec['scaffold_path']}")
        return rec
    if not reprocessing and index_carries_slug(slug, ctx["root"]):
        rec["status"] = "FAILED"
        rec["notes"].append(f"index guard: sources.jsonl already carries {slug}")
        return rec

    if not recovered:
        try:
            write_raw_mirror(mirror_path, mirror_text, dry_run=ctx["dry_run"])
        except ClobberError as exc:
            rec["status"] = "FAILED"
            rec["notes"].append(f"clobber guard: {exc}")
            return rec
    rec["mirror"] = mirror_path
    rec["recovered"] = recovered

    scaffold = render_source_scaffold(meeting, slug, ctx["template"], ctx["today"])
    if recovered:
        scaffold = scaffold.replace(
            f"origin: raw/transcripts/{slug}.md",
            f"origin: raw/transcripts/{slug}{MIRROR_SUFFIX}.md")
        scaffold = scaffold.replace(
            f"Raw mirror: `wiki/raw/transcripts/{slug}.md`",
            f"Raw mirror: `wiki/raw/transcripts/{slug}{MIRROR_SUFFIX}.md`")
        scaffold = _insert_recovered_block(scaffold, ctx["today"], recover_verdict)
    rec["scaffold_path"] = os.path.join(ctx["sources_dir"], f"{slug}.md")
    if ctx["write_scaffold"]:
        if os.path.exists(rec["scaffold_path"]):
            rec["status"] = "FAILED"
            rec["notes"].append("source page already exists: "
                                f"{rec['scaffold_path']}")
            return rec
        if not ctx["dry_run"]:
            os.makedirs(ctx["sources_dir"], exist_ok=True)
            with open(rec["scaffold_path"], "w", encoding="utf-8") as f:
                f.write(scaffold)
    else:
        rec["scaffold"] = scaffold

    try:
        rec["index_line"] = append_index_line(meeting, slug, ctx["root"],
                                              dry_run=ctx["dry_run"],
                                              replace=reprocessing)
    except ClobberError as exc:
        rec["status"] = "FAILED"
        rec["notes"].append(f"index guard: {exc}")
        return rec
    rec["log_line"] = append_log_line(meeting, slug, ctx["root"],
                                      dry_run=ctx["dry_run"], today=ctx["today"])
    ctx["index_slugs"].add(slug)
    return rec


def build_context(args, run_checks, retranscribe=None):
    index_slugs, series_counts, candidates = read_index_slugs(REPO)
    reprocess = getattr(args, "reprocess", False)
    reprocess_eligible = reprocess_eligible_slugs(candidates, SOURCES_DIR) if reprocess else set()
    return {
        "index_slugs": index_slugs,
        "series_counts": series_counts,
        "reprocess": reprocess,
        "reprocess_eligible": reprocess_eligible,
        "prior_pages": read_prior_pages(SOURCES_DIR),
        "scorer": load_quality_scorer(),
        "raw_dir": RAW_DIR,
        "sources_dir": SOURCES_DIR,
        "template": TEMPLATE,
        # One key for the repo root. Upstream carried "hub" and "root" side by
        # side with the same value; they were always the same thing.
        "root": REPO,
        "today": dt.date.today().isoformat(),
        "dry_run": args.dry_run,
        "write_scaffold": args.write_scaffold,
        "auto_retranscribe": getattr(args, "auto_retranscribe", False),
        "retranscribe": retranscribe or default_retranscribe_runner,
        "run_checks": run_checks,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def collect(args):
    """Run every mechanical adapter the requested source covers.

    Fireflies is the only one shipped. A capture tool without a REST API is
    landed by the skill through the scaffold path and never reaches here.
    """
    result = AdapterResult()
    if args.source in ("fireflies", "all"):
        try:
            ff = fetch_fireflies(args.since, args.until,
                                 with_sentences=not args.diff_only)
            result.meetings += ff.meetings
            result.flags += ff.flags
        except ApiError as exc:
            result.flags.append({"id": "fireflies", "reason": f"adapter failed: {exc}"})
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    # The flag documents the adapter seam: a new source adds an adapter and a
    # choice here, and the pipeline below never forks.
    p.add_argument("--source", choices=["fireflies", "all"], default="all")
    p.add_argument("--dry-run", action="store_true", help="run every stage, write nothing")
    p.add_argument("--diff-only", action="store_true",
                   help="list provider meetings absent from the index, then exit")
    p.add_argument("--write-scaffold", action="store_true",
                   help="write source-page scaffolds instead of printing them")
    p.add_argument("--auto-retranscribe", action="store_true",
                   help="on a garbled capture, run wiki_retranscribe.py inline "
                        "(verify-or-abort, $0.50/meeting cap) and land the "
                        "recovered mirror; fall back to a ledger flag on abort. "
                        "Off by default so --dry-run and --diff-only never spend.")
    p.add_argument("--reprocess", action="store_true",
                   help="re-ingest a garble ledger line already in the index "
                        "(one with no source page yet, not one marked "
                        "unrecoverable); replaces the ledger line on success. "
                        "Pair with --auto-retranscribe to actually heal it.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import wiki_check as tt

    acquired = collect(args)
    meetings, dedupe_flags = dedupe_captures(acquired.meetings, strict=not args.diff_only)
    flags = acquired.flags + dedupe_flags

    if args.diff_only:
        index_slugs, series_counts, candidates = read_index_slugs(REPO)
        prior = read_prior_pages(SOURCES_DIR)
        eligible = reprocess_eligible_slugs(candidates, SOURCES_DIR) if args.reprocess else set()
        missing = []
        for m in meetings:
            body, reason = resolve_series_slug(m, series_counts, prior)
            slug = f"{m.date}_{body}"
            if slug not in index_slugs:
                missing.append({"slug": slug, "date": m.date, "title": m.title,
                                "source": m.source, "provider_id": m.provider_id,
                                "needs_judgment": reason})
            elif slug in eligible:
                missing.append({"slug": slug, "date": m.date, "title": m.title,
                                "source": m.source, "provider_id": m.provider_id,
                                "needs_judgment": "reprocess: garble ledger line"})
        payload = {"mode": "diff-only", "since": args.since, "until": args.until,
                   "provider_meetings": len(meetings), "missing": missing,
                   "flags": flags}
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Provider meetings {args.since}..{args.until}: {len(meetings)}")
            print(f"Absent from the index: {len(missing)}")
            for row in missing:
                extra = f"  [{row['needs_judgment']}]" if row["needs_judgment"] else ""
                print(f"  - {row['slug']} | {row['source']} | {row['title']}{extra}")
            for f in flags:
                print(f"  ! {f.get('file') or f.get('id')}: {f['reason']}")
        return 0

    ctx = build_context(args, tt.run_checks)
    records = [land_meeting(m, ctx) for m in sorted(meetings, key=lambda m: m.date)]
    undistilled = count_undistilled(SOURCES_DIR)
    payload = {"since": args.since, "until": args.until, "dry_run": args.dry_run,
               "records": records, "flags": flags, "undistilled_sources": undistilled}

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Ingest {args.since}..{args.until}"
          + ("  (dry run, nothing written)" if args.dry_run else ""))
    for rec in records:
        print(f"  {rec['status']:8} {rec.get('slug', '?')} | {rec['title']}")
        for note in rec["notes"]:
            print(f"           {note}")
    for f in flags:
        print(f"  FLAG     {f.get('file') or f.get('id')}: {f['reason']}")
    if not args.write_scaffold:
        for rec in records:
            if rec.get("scaffold"):
                print(f"\n----- scaffold: wiki/sources/{rec['slug']}.md -----")
                print(rec["scaffold"])
    print(f"\nUndistilled source pages: {undistilled}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
