#!/usr/bin/env python3
"""One mechanical checker for the wiki.

Takes a wiki root, runs every mechanical schema rule against every page, and
prints one line per violation:

    <page> | <rule_id> | <fix>

Exits non-zero when any page violates a rule, zero when the wiki is clean. This
is the single enforcement point for the wiki schema; it replaces wiki_validate,
the mechanical half of wiki_health, wiki_signals_check, wiki_distill_check's
`check`, and wiki_unresolved_targets, and folds in the transcript truncation
check.

Mechanical checks only. Semantic judgment (orphans, tag sprawl, distill yield,
current-truth staleness, missing-page thresholds) stays with the wiki-triage
skill and is not enforced here.

Usage:
  python3 scripts/wiki_check.py                 # the repo's own wiki/
  python3 scripts/wiki_check.py path/to/wiki    # any wiki root
  python3 scripts/wiki_check.py --json

The positional argument is the wiki directory itself (the folder holding
sources/, entities/, ...), not the repo root. It defaults to the wiki beside
this script's repo.

This module is also imported by wiki_ingest (for run_checks) and
wiki_distill_apply (for check_file, frontmatter_lines, and the evidence-bullet
constants); those names are part of the module's contract, keep them stable.
"""

import argparse
import datetime
import json
import os
import re
import sys
from collections import namedtuple

# ---------------------------------------------------------------------------
# CONFIG. Enums and required-key tables. Edited as the schema evolves.
# ---------------------------------------------------------------------------

TYPES = ["source", "entity", "concept", "synthesis", "archive"]
KNOWN_PROJECTS = ["work", "personal", "health", "life"]
CONFIDENTIAL_VALUES = ["finance", "personnel", "legal"]
CLASS_VALUES = ["primary", "external"]
VIA_VALUES = [
    "clipper", "fetcher", "paste", "fireflies", "drive_export", "gmail",
]
CONTEXT_VALUES = ["internal", "external"]
SUBTYPE_VALUES = ["person", "org", "product"]
STORAGE_VALUES = ["verbatim", "digest"]
RETRIEVAL_VALUES = ["full", "partial", "excerpts"]

SCALAR_ENUMS = {
    "type": TYPES,
    "class": CLASS_VALUES,
    "via": VIA_VALUES,
    "context": CONTEXT_VALUES,
    "subtype": SUBTYPE_VALUES,
    "storage": STORAGE_VALUES,
    "retrieval": RETRIEVAL_VALUES,
}

# Required keys per page type. `type` and `tags` are required on every page
# (tags is enforced separately below).
REQUIRED_BY_TYPE = {
    "source": ["type", "project", "created", "via"],
    "entity": ["type", "subtype"],
    "concept": ["type"],
    "synthesis": ["type"],
    "archive": ["type"],
}
REQUIRED_ALWAYS = ["type"]

DATE_FIELDS = ["created", "updated", "ingested", "distilled", "triaged"]
RECOVERED_SUBKEYS = ["engine", "date"]

# Content folders the checker walks as pages.
WIKI_FOLDERS = ["sources", "entities", "concepts", "synthesis", "confidential", "archive"]
# Instruction files, not content: the schema and the CLAUDE.md pointers beside
# it. `confidential/` carries a pair of these, so the walk must skip them by
# name or every run reports the schema as a page missing its frontmatter.
INSTRUCTION_FILES = {"AGENTS.md", "CLAUDE.md"}
# Living pages carry the word budget and the tiers.
LIVING_DIRS = ("entities", "concepts", "synthesis", "confidential")

# Word budgets (schema Hygiene + Rule 1).
WIKI_PAGE_BUDGET = 2000   # living page total
TRUTH_WORD_CAP = 250      # `# Current truth` section body
DIGEST_WORD_CAP = 2000    # source-page `# Summary` digest

# Sections a source page must carry (schema Rule 4).
REQUIRED_SOURCE_SECTIONS = ["# Signals", "# Distilled"]

# Evidence-bullet house format (schema Evidence format; distill enforces it).
TRUST_CLASSES = ["primary", "external", "inference"]
EVIDENCE_HEADING = "# Evidence"
BULLET_RE = re.compile(
    r"^- (?P<date>\d{4}-\d{2}-\d{2})"
    r" \| (?P<claim>.+?)"
    r" \| (?P<tags>#[a-z0-9_]+(?: +#[a-z0-9_]+)*)"
    r" \| Source: (?P<source>.+?)"
    r" \((?P<cls>" + "|".join(TRUST_CLASSES) + r")(?P<qualifier>[^)]*)\)$"
)
DATED_BULLET_RE = re.compile(r"^- \d{4}-\d{2}-\d{2} \|")
BULLET_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")

# A body wikilink, target normalized (anchor and alias stripped).
WIKILINK_RE = re.compile(r"\[\[([^\]\[|#]+)(?:#[^\]\[|]*)?(?:\|[^\]\[]*)?\]\]")
# schema and template examples, never real link targets.
LINK_PLACEHOLDERS = {"page", "source_page", "slug", "wikilink", "wikilinks",
                     "note name", "entity", "concept", "target"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG_SLUG_RE = re.compile(r"[a-z0-9_]+")
SIGNALS_HEADING = "# Signals"
THIN_FLAG_RE = re.compile(r"\*\*\s*signals:\s*thin", re.IGNORECASE)
SIG_BULLET_RE = re.compile(r"^- +\S")
HINT_RE = re.compile(r"^- +\*\*[^*]+\*\*")
MIN_BULLETS = 1
MIN_HINT_COVERAGE = 0.5

DEFAULT_WIKI = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")),
    "wiki",
)

# ---------------------------------------------------------------------------
# Frontmatter parser (hand-rolled, stdlib only). Same behaviour the retired
# wiki_validate carried: inline lists, block lists, one level of nesting.
# ---------------------------------------------------------------------------


def split_frontmatter(text):
    """The raw frontmatter body lines, or None when there is no block."""
    span = frontmatter_lines(text)
    if span is None:
        return None
    return text.split("\n")[span[0]:span[1]]


def frontmatter_lines(text):
    """(start, end) indices of the frontmatter body, or None. Used by importers."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return (1, i)
    return None


def strip_quotes(s):
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def split_top_level(inner):
    parts, depth, buf = [], 0, []
    for ch in inner:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p for p in parts if p.strip() != ""]


def strip_inline_comment(raw):
    """Drop a trailing YAML comment from a scalar or inline list.

    Real YAML treats ` # ...` outside quotes and brackets as a comment; this
    hand-rolled parser did not, so a template writing its option hints inline

        project:                # work | personal | health | life

    read the whole hint as the value. Bracket and quote depth are tracked so a
    `#tag_slug` inside a list or a quoted string survives.
    """
    out, depth, quote = [], 0, None
    for i, ch in enumerate(raw):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "#" and depth == 0 and (i == 0 or raw[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out)


def parse_scalar(raw):
    raw = strip_inline_comment(raw).strip()
    if raw == "":
        return ""
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if inner == "":
            return []
        return [strip_quotes(p.strip()) for p in split_top_level(inner)]
    return strip_quotes(raw)


def parse_frontmatter(text):
    """(data, ok). ok is False when the file has no frontmatter block."""
    raw_lines = split_frontmatter(text)
    if raw_lines is None:
        return {}, False

    data = {}
    current_key = None
    current_kind = None  # "block_list" or "nested"

    for line in raw_lines:
        if line.strip() == "" or line.lstrip().startswith("#"):
            continue
        indented = line[:1] in (" ", "\t")
        if indented:
            stripped = line.strip()
            if current_key is None:
                continue
            if stripped.startswith("- "):
                if current_kind != "block_list":
                    data[current_key] = []
                    current_kind = "block_list"
                data[current_key].append(strip_quotes(stripped[2:].strip()))
            elif ":" in stripped:
                if current_kind != "nested":
                    data[current_key] = {}
                    current_kind = "nested"
                sub_key, _, sub_val = stripped.partition(":")
                data[current_key][sub_key.strip()] = parse_scalar(sub_val)
            continue
        if line.startswith("- "):
            if current_key is not None:
                if current_kind != "block_list":
                    data[current_key] = []
                    current_kind = "block_list"
                data[current_key].append(strip_quotes(line[2:].strip()))
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        data[key.strip()] = parse_scalar(val)
        current_key = key.strip()
        current_kind = None

    return data, True


def as_list(value):
    if value == "" or value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return []
    return [value]


# ---------------------------------------------------------------------------
# Section helpers
# ---------------------------------------------------------------------------


def section_body(text, heading):
    """Body of a `# Heading` section, up to the next `#..#` heading."""
    pattern = re.compile(r"(?m)^%s[^\n]*\n" % re.escape(heading))
    m = pattern.search(text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"(?m)^#{1,6} ", rest)
    return rest[:nxt.start()] if nxt else rest


def has_heading(text, heading):
    return any(line.strip() == heading for line in text.split("\n"))


# ---------------------------------------------------------------------------
# Tag registry
# ---------------------------------------------------------------------------


def load_tag_registry(path):
    """Every registered slug plus every alias, from the markdown tables."""
    known = set()
    if not os.path.exists(path):
        return known, False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            slug = cells[0]
            if slug.lower() in ("slug", "canonical", "") or set(slug) <= set("-: "):
                continue
            if not TAG_SLUG_RE.fullmatch(slug):
                continue
            known.add(slug)
            for alias in cells[1].split(","):
                alias = alias.strip()
                if alias and TAG_SLUG_RE.fullmatch(alias):
                    known.add(alias)
    return known, True


# ---------------------------------------------------------------------------
# Transcript truncation. Ported verbatim; run_checks is imported by wiki_ingest
# keep the signature and Result shape stable.
# ---------------------------------------------------------------------------

Result = namedtuple("Result", "name status detail")

_TURN = re.compile(r"^\*\*(?P<speaker>.+?)\*\*\s*(?:\[(?P<ts>[\d:]+)\])?\s*:\s*(?P<text>.*)$")
GAP_FLOOR_SEC = 10 * 60
GAP_FRACTION = 0.25
DURATION_TOLERANCE_FRACTION = 0.15
DURATION_TOLERANCE_SEC = 5 * 60
TAIL_FRACTION = 0.20


def parse_ts(raw):
    parts = [int(p) for p in raw.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3], parts[-2], parts[-1]
    return h * 3600 + m * 60 + s


def parse_turns(text):
    body = text
    marker = "\n---\n"
    if marker in body:
        body = body.split(marker, 1)[1]
    turns = []
    for line in body.splitlines():
        m = _TURN.match(line.strip())
        if not m:
            continue
        ts = parse_ts(m.group("ts")) if m.group("ts") else None
        turns.append((m.group("speaker").strip(), ts, m.group("text").strip()))
    return turns


def _mmss(secs):
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}"


def run_checks(mirror_text, duration_min=None, speakers=None):
    """Run all five truncation tripwires. Returns a list of Result."""
    speakers = [s.strip() for s in (speakers or []) if s and s.strip()]
    turns = parse_turns(mirror_text)
    stamps = [t[1] for t in turns if t[1] is not None]
    dur_sec = float(duration_min) * 60 if duration_min else None
    results = []

    if not turns:
        return [Result("duration_accounting", "FAIL", "no turns parsed from the mirror"),
                Result("internal_gap", "FAIL", "no turns parsed from the mirror"),
                Result("tail_check", "FAIL", "no turns parsed from the mirror"),
                Result("roster_coverage", "FAIL", "no turns parsed from the mirror"),
                Result("timestamp_continuity", "FAIL", "no turns parsed from the mirror")]

    no_ts = not stamps
    no_dur = dur_sec is None or dur_sec <= 0

    if no_ts:
        results.append(Result("duration_accounting", "WARN",
                              "capture carries no timestamps, cannot account for duration"))
    elif no_dur:
        results.append(Result("duration_accounting", "WARN",
                              "no stated duration to compare against"))
    else:
        last = max(stamps)
        tolerance = max(dur_sec * DURATION_TOLERANCE_FRACTION, DURATION_TOLERANCE_SEC)
        gap = dur_sec - last
        detail = (f"last turn {_mmss(last)} vs stated {_mmss(dur_sec)}, "
                  f"tolerance {_mmss(tolerance)}")
        results.append(Result("duration_accounting",
                              "PASS" if abs(gap) <= tolerance else "FAIL", detail))

    if no_ts:
        results.append(Result("internal_gap", "WARN",
                              "capture carries no timestamps, cannot measure gaps"))
    else:
        limit = max(GAP_FLOOR_SEC, (dur_sec or 0) * GAP_FRACTION)
        worst, worst_at = 0, None
        for prev, cur in zip(stamps, stamps[1:]):
            if cur - prev > worst:
                worst, worst_at = cur - prev, prev
        if worst > limit:
            results.append(Result("internal_gap", "FAIL",
                                  f"silent gap of {_mmss(worst)} after {_mmss(worst_at)}, "
                                  f"limit {_mmss(limit)}"))
        else:
            results.append(Result("internal_gap", "PASS",
                                  f"largest gap {_mmss(worst)}, limit {_mmss(limit)}"))

    if no_ts:
        results.append(Result("tail_check", "WARN",
                              "capture carries no timestamps, cannot check the tail"))
    elif no_dur:
        results.append(Result("tail_check", "WARN", "no stated duration to compare against"))
    else:
        last = max(stamps)
        missing = dur_sec - last
        if missing > dur_sec * TAIL_FRACTION:
            results.append(Result("tail_check", "FAIL",
                                  f"transcript ends {_mmss(missing)} early, over "
                                  f"{int(TAIL_FRACTION * 100)}% of {_mmss(dur_sec)}"))
        else:
            results.append(Result("tail_check", "PASS",
                                  f"ends {_mmss(max(0, missing))} before stated duration"))

    if not speakers:
        results.append(Result("roster_coverage", "WARN", "no expected speaker roster given"))
    else:
        heard = {t[0] for t in turns}
        missing = [s for s in speakers if s not in heard]
        if missing:
            results.append(Result("roster_coverage", "WARN",
                                  "never speaks: " + ", ".join(missing)
                                  + " (silent observer or lost audio, judgment)"))
        else:
            results.append(Result("roster_coverage", "PASS",
                                  f"all {len(speakers)} listed speakers appear"))

    if no_ts:
        results.append(Result("timestamp_continuity", "WARN",
                              "capture carries no timestamps"))
    else:
        breaks = [(i, prev, cur) for i, (prev, cur)
                  in enumerate(zip(stamps, stamps[1:])) if cur < prev]
        if breaks:
            i, prev, cur = breaks[0]
            results.append(Result("timestamp_continuity", "FAIL",
                                  f"{len(breaks)} backward jump(s); first at turn {i + 2}: "
                                  f"{_mmss(prev)} then {_mmss(cur)}"))
        else:
            results.append(Result("timestamp_continuity", "PASS",
                                  f"{len(stamps)} timestamps non-decreasing"))
    return results


def read_expected(text):
    """Duration and speakers from a source page or a raw mirror header."""
    duration = None
    dm = re.search(r"^[-*]?\s*(?:\*\*)?Duration:?(?:\*\*)?\s*(\d+)\s*min", text, re.M)
    if dm:
        duration = int(dm.group(1))
    speakers = []
    sm = re.search(r"^[-*]?\s*(?:\*\*)?Speakers:?(?:\*\*)?\s*(.+)$", text, re.M)
    if sm:
        speakers = [s.strip() for s in sm.group(1).split(",") if s.strip()]
    if not speakers:
        pm = re.search(r"^participants:\s*\[(.*?)\]", text, re.M | re.S)
        if pm:
            speakers = [p.strip().strip('"').strip("'")
                        for p in pm.group(1).split(",") if p.strip()]
    return duration, speakers


# ---------------------------------------------------------------------------
# Evidence-bullet scan. check_file keeps the retired distill_check contract
# (append {file,line,problem,detail} dicts); wiki_distill_apply imports it.
# ---------------------------------------------------------------------------


def evidence_block(text):
    out = []
    inside = False
    for n, line in enumerate(text.split("\n"), start=1):
        if line.strip() == EVIDENCE_HEADING:
            inside = True
            continue
        if inside and line.startswith("# "):
            break
        if inside:
            out.append((n, line))
    return out, inside


def check_file(path, rel, out):
    """Validate one page's `# Evidence` bullets. Appends violation dicts to out."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for line_no, problem, detail, _rule in scan_evidence(text):
        out.append({"file": rel, "line": line_no, "problem": problem, "detail": detail})


def scan_evidence(text):
    """Yield (line_no, problem, detail, rule_id) for every bad evidence bullet.

    rule_id splits the house-format defects (sourced-claim) from the ordering
    defects (evidence-append-only).
    """
    lines, has_section = evidence_block(text)
    if not has_section:
        return
    last_date = None
    for line_no, line in lines:
        if not line.startswith("- "):
            continue
        if not DATED_BULLET_RE.match(line):
            yield (line_no, "bullet does not open with `- YYYY-MM-DD |`",
                   line.strip()[:120], "sourced-claim")
            continue
        m = BULLET_RE.match(line)
        if not m:
            yield (line_no,
                   "bullet does not match the house format "
                   "`- DATE | claim | #tags | Source: [[page]] (class)`",
                   line.strip()[:120], "sourced-claim")
            continue
        if not BULLET_WIKILINK_RE.search(m.group("source")):
            yield (line_no, "source carries no [[wikilink]]",
                   m.group("source")[:120], "sourced-claim")
        date = m.group("date")
        try:
            datetime.date.fromisoformat(date)
        except ValueError:
            yield (line_no, "not a real calendar date", date, "evidence-append-only")
            continue
        if last_date is not None and date < last_date:
            yield (line_no, "out of date order (follows %s)" % last_date,
                   date, "evidence-append-only")
        last_date = max(last_date, date) if last_date else date


# ---------------------------------------------------------------------------
# Signals completeness (ported from wiki_signals_check.assess)
# ---------------------------------------------------------------------------


def signals_bullets(text):
    out = []
    inside = False
    for line in text.split("\n"):
        stripped = line.rstrip()
        if stripped.strip() == SIGNALS_HEADING:
            inside = True
            continue
        if inside and stripped.startswith("# "):
            break
        if inside and SIG_BULLET_RE.match(stripped):
            out.append(stripped)
    return out


def signals_reasons(text):
    """Reasons a source page's Signals section is thin, empty when it is fine."""
    reasons = []
    section = has_heading(text, SIGNALS_HEADING)
    bullets = signals_bullets(text)
    n = len(bullets)
    hinted = sum(1 for b in bullets if HINT_RE.match(b))
    coverage = (hinted / n) if n else 0.0
    if not section:
        reasons.append("no # Signals section")
    if n < MIN_BULLETS:
        reasons.append("fewer than %d signal bullet(s) (%d)" % (MIN_BULLETS, n))
    if THIN_FLAG_RE.search(text):
        reasons.append("page carries a **Signals: thin** caveat")
    if n and coverage < MIN_HINT_COVERAGE:
        reasons.append("target-hint coverage %d%% < 50%% (%d of %d bullets hinted)"
                       % (round(coverage * 100), hinted, n))
    return reasons


# ---------------------------------------------------------------------------
# Unresolved signal targets (ported from wiki_unresolved_targets)
# ---------------------------------------------------------------------------


def near_matches(target, slugs):
    """Existing slugs that extend the target at an underscore boundary."""
    out = []
    for slug in slugs:
        if slug == target:
            continue
        if slug.startswith(target + "_") or target.startswith(slug + "_"):
            out.append(slug)
    return sorted(set(out))


def signal_targets(text):
    """[[target]]s in the `# Signals` bullet prefixes of one source page."""
    m = re.search(r"^# Signals$(.*?)(?=^# |\Z)", text, re.S | re.M)
    if not m:
        return []
    found = []
    for line in m.group(1).split("\n"):
        if not line.startswith("- "):
            continue
        prefix = line.split("|")[0]
        for t in re.findall(r"\[\[([^\]]+)\]\]", prefix):
            found.append(t.split("|")[0].strip())
    return found


# ---------------------------------------------------------------------------
# The rule engine
# ---------------------------------------------------------------------------

Violation = namedtuple("Violation", "page rule fix")


def is_source(rel):
    return rel.split("/")[0] == "sources"


def is_living(rel):
    return rel.split("/")[0] in LIVING_DIRS


def is_confidential(rel):
    return rel.split("/")[0] == "confidential"


def check_frontmatter(rel, data, ok, known_tags, out):
    """Frontmatter schema rules -> `frontmatter`; tag rules -> `tag-unregistered`."""
    if not ok:
        out.append(Violation(rel, "frontmatter",
                             "no frontmatter block (add --- fences)"))
        return

    page_type = data.get("type", "")
    if isinstance(page_type, list):
        page_type = page_type[0] if page_type else ""

    required = REQUIRED_BY_TYPE.get(page_type, REQUIRED_ALWAYS)
    for key in required:
        value = data.get(key, None)
        if value is None:
            out.append(Violation(rel, "frontmatter", "%s: required key missing" % key))
        elif value == "" or value == []:
            out.append(Violation(rel, "frontmatter", "%s: required key is empty" % key))

    for key, allowed in SCALAR_ENUMS.items():
        if key not in data:
            continue
        value = data[key]
        if value == "" or isinstance(value, (list, dict)):
            if isinstance(value, (list, dict)) and value:
                out.append(Violation(rel, "frontmatter",
                                     "%s: expected a single value, got a list or block" % key))
            continue
        if value not in allowed:
            out.append(Violation(rel, "frontmatter",
                                 "%s: unknown value '%s', use one of: %s"
                                 % (key, value, " | ".join(allowed))))

    if "project" in data:
        for value in as_list(data["project"]):
            if value not in KNOWN_PROJECTS:
                out.append(Violation(rel, "frontmatter",
                                     "project: '%s' is not one of %s"
                                     % (value, " | ".join(KNOWN_PROJECTS))))

    if "confidential" in data:
        conf = data["confidential"]
        if isinstance(conf, str) and conf:
            out.append(Violation(rel, "frontmatter",
                                 "confidential: must be a list, got the bare value '%s'" % conf))
        for value in as_list(conf):
            if value not in CONFIDENTIAL_VALUES:
                out.append(Violation(rel, "frontmatter",
                                     "confidential: unknown value '%s', use any of: %s"
                                     % (value, " | ".join(CONFIDENTIAL_VALUES))))

    for key in DATE_FIELDS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, str):
            value = value.split("#", 1)[0].strip()
        if value and not DATE_RE.match(value):
            out.append(Violation(rel, "frontmatter",
                                 "%s: not a YYYY-MM-DD date: '%s'" % (key, value)))

    if "recovered" in data:
        rec = data["recovered"]
        if not isinstance(rec, dict):
            out.append(Violation(rel, "frontmatter",
                                 "recovered: must be a block with engine and date subkeys"))
        else:
            for sub in RECOVERED_SUBKEYS:
                if sub not in rec or rec[sub] == "":
                    out.append(Violation(rel, "frontmatter",
                                         "recovered.%s: required subkey missing or empty" % sub))

    if "tags" not in data:
        out.append(Violation(rel, "frontmatter", "tags: required key missing"))
    else:
        tags = as_list(data["tags"])
        if not tags:
            out.append(Violation(rel, "frontmatter", "tags: required key is empty"))
        for tag in tags:
            slug = tag.lstrip("#").strip()
            if slug and slug not in known_tags:
                out.append(Violation(rel, "tag-unregistered",
                                     "register '%s' in metadata/tag_registry.md, or fix the slug"
                                     % slug))


def check_page(rel, text, known_tags, known_pages, known_slugs, out):
    data, ok = parse_frontmatter(text)
    check_frontmatter(rel, data, ok, known_tags, out)

    # Evidence bullets: house format (sourced-claim) and order (append-only).
    for _line, problem, _detail, rule in scan_evidence(text):
        if rule == "sourced-claim":
            out.append(Violation(rel, "sourced-claim", problem))
        else:
            out.append(Violation(rel, "evidence-append-only", problem))

    # Evidence must not leak into synthesis: no dated evidence bullet inside
    # `# Current truth` (schema Rule 6).
    truth = section_body(text, "# Current truth")
    for line in truth.split("\n"):
        if DATED_BULLET_RE.match(line.strip()):
            out.append(Violation(rel, "evidence-synthesis-split",
                                 "move the dated evidence bullet out of `# Current truth` "
                                 "into `# Evidence`"))
            break

    # Word budgets.
    if is_living(rel):
        total = len(text.split())
        if total > WIKI_PAGE_BUDGET:
            out.append(Violation(rel, "word-budget",
                                 "living page is %dw > %dw, rotate old evidence to archive"
                                 % (total, WIKI_PAGE_BUDGET)))
    truth_words = len(truth.split())
    if truth_words > TRUTH_WORD_CAP:
        out.append(Violation(rel, "word-budget",
                             "`# Current truth` is %dw > %dw, trim or demote to Evidence"
                             % (truth_words, TRUTH_WORD_CAP)))
    if is_source(rel):
        digest = section_body(text, "# Summary (factual)") or section_body(text, "# Summary")
        dwords = len(digest.split())
        if dwords > DIGEST_WORD_CAP:
            out.append(Violation(rel, "word-budget",
                                 "`# Summary` digest is %dw > %dw, tighten or split"
                                 % (dwords, DIGEST_WORD_CAP)))

    # Source-only rules.
    if is_source(rel):
        for heading in REQUIRED_SOURCE_SECTIONS:
            if not has_heading(text, heading):
                out.append(Violation(rel, "required-sections",
                                     "add a `%s` section" % heading))
        if "retrieval" not in data:
            out.append(Violation(rel, "retrieval-declared",
                                 "declare `retrieval:` (full | partial | excerpts)"))
        if "distilled" not in data:
            out.append(Violation(rel, "distilled-marker",
                                 "add a `distilled:` field (empty = awaiting distill)"))
        reasons = signals_reasons(text)
        if reasons:
            out.append(Violation(rel, "signals-thin", "; ".join(reasons)))

    # Confidential routing: a page in confidential/ must declare its lens.
    if is_confidential(rel):
        if not as_list(data.get("confidential")):
            out.append(Violation(rel, "confidential-routing",
                                 "confidential/ page must carry a non-empty `confidential:` lens"))

    # Link resolution and wrong-slug signal targets.
    sig = set(signal_targets(text))
    for target in {t.strip() for t in WIKILINK_RE.findall(text) if t.strip()}:
        if target in known_pages:
            continue
        bare = target.split("/")[-1].lower()
        if bare in LINK_PLACEHOLDERS or bare in known_tags:
            continue
        near = near_matches(target.split("/")[-1], known_slugs)
        if near and target in sig:
            out.append(Violation(rel, "unresolved-target",
                                 "`[[%s]]` is a wrong slug, the page is %s"
                                 % (target, ", ".join(near))))
        elif not near:
            out.append(Violation(rel, "link-resolve",
                                 "`[[%s]]` resolves to no page, create it or fix the link"
                                 % target))


def check_truncation(rel, text, wiki, out):
    """Run the truncation tripwires on a source page's raw mirror when present."""
    origin = None
    span = frontmatter_lines(text)
    if span is not None:
        lines = text.split("\n")
        for i in range(span[0], span[1]):
            if lines[i].startswith("origin:"):
                origin = lines[i][len("origin:"):].strip()
                break
    if not origin:
        return
    # Truncation tripwires are for meeting transcripts only. Non-meeting
    # sources (emails, decks, PDFs, clippings) point at raw/documents or
    # raw/clippings mirrors that legitimately have no speaker turns, so
    # skip anything whose origin is not a transcript.
    norm_origin = origin[len("wiki/"):] if origin.startswith("wiki/") else origin
    if not norm_origin.startswith("raw/transcripts/"):
        return
    candidates = [
        os.path.join(wiki, origin),
        os.path.join(os.path.dirname(wiki), origin),
        origin,
    ]
    mirror = next((c for c in candidates if os.path.isfile(c)), None)
    if mirror is None:
        return  # raw transcripts are gitignored, absent is not a violation
    with open(mirror, encoding="utf-8", errors="replace") as fh:
        mirror_text = fh.read()
    duration, speakers = read_expected(text)
    for r in run_checks(mirror_text, duration, speakers):
        if r.status == "FAIL":
            out.append(Violation(rel, "transcript-truncation",
                                 "%s: %s" % (r.name, r.detail)))


# ---------------------------------------------------------------------------
# Walk and drive
# ---------------------------------------------------------------------------


def wiki_pages(wiki):
    """(relpath-from-wiki-without-ext, abspath) for content pages the checker walks."""
    out = []
    for folder in WIKI_FOLDERS:
        base = os.path.join(wiki, folder)
        for dirpath, dirnames, names in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in (".obsidian", "__pycache__")]
            for name in sorted(names):
                if name.endswith(".md") and name not in INSTRUCTION_FILES:
                    full = os.path.join(dirpath, name)
                    key = os.path.relpath(full, wiki)[:-3].replace(os.sep, "/")
                    out.append((key, full))
    return out


def all_page_addresses(wiki):
    """Every page's bare slug and vault-relative path, for link resolution."""
    slugs, addresses = set(), set()
    for dirpath, dirnames, names in os.walk(wiki):
        dirnames[:] = [d for d in dirnames if d not in (".obsidian", "__pycache__", "raw")]
        for name in names:
            if not name.endswith(".md") or name in INSTRUCTION_FILES:
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, wiki)[:-3].replace(os.sep, "/")
            slugs.add(rel.split("/")[-1])
            addresses.add(rel)
    return slugs, slugs | addresses


def run(wiki):
    """Return (violations, files_checked, registry_found)."""
    registry_path = os.path.join(wiki, "metadata", "tag_registry.md")
    known_tags, found = load_tag_registry(registry_path)
    if not found:
        return None, 0, False

    known_slugs, known_pages = all_page_addresses(wiki)
    pages = wiki_pages(wiki)
    out = []
    for rel, full in pages:
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        check_page(rel, text, known_tags, known_pages, known_slugs, out)
        if is_source(rel):
            check_truncation(rel, text, wiki, out)
    out.sort(key=lambda v: (v.page, v.rule, v.fix))
    return out, len(pages), True


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a wiki root against the schema.")
    parser.add_argument("wiki_root", nargs="?", default=None,
                        help="the wiki directory (default: this repo's wiki/)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    wiki = os.path.abspath(args.wiki_root) if args.wiki_root else DEFAULT_WIKI
    if not os.path.isdir(wiki):
        print("no wiki root at: %s" % wiki, file=sys.stderr)
        return 2

    violations, checked, found = run(wiki)
    if not found:
        print("tag registry not found: %s"
              % os.path.join(wiki, "metadata", "tag_registry.md"), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "wiki": wiki,
            "files_checked": checked,
            "violations": [v._asdict() for v in violations],
            "count": len(violations),
        }, indent=2))
    else:
        for v in violations:
            print("%s | %s | %s" % (v.page, v.rule, v.fix))
        print("\n%d page(s) checked, %d violation(s)." % (checked, len(violations)))

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
