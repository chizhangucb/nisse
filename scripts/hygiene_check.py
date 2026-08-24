#!/usr/bin/env python3
"""Workspace health checker for the /hygiene skill.

Deterministic, read-only. Walks the repo and emits findings grouped into 6
categories: filesystem cruft, git hygiene, freshness, operating-doc health,
structural loose ends, and the mechanical half of wiki health. Never deletes
or edits anything; the skill drives confirm-to-fix. Stdlib only; defensive
(a broken check degrades to a note, never a crash).

Each finding is one line:
  [severity][tag] group | message | path
where tag is `auto-safe` (zero-risk cleanup) or `judgment` (needs a call).

Run from the repo root:  python3 scripts/hygiene_check.py
Override the scanned root with $HYGIENE_ROOT or main(root=...).
"""
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime

# ---- config (the owner-tunable seam) ----------------------------------------

# Your approved personal remote owner (e.g. "yourhandle"). Empty = the
# remote-owner check is skipped. Set it the day you add a remote.
APPROVED_REMOTE_OWNER = ""

# Tracker-drift checks (tier-2 Linear connector) are OFF by default. Turn on
# with NISSE_TRACKER_DRIFT=1 once a tracker is wired; requires
# scripts/ticket_tracker.py (your own integration) to exist.
TRACKER_DRIFT = os.environ.get("NISSE_TRACKER_DRIFT") == "1"

THRESHOLD_DAYS = 14          # untouched/uncommitted staleness
LIVE_DOC_STALE_DAYS = 31     # priorities.md live heading, decisions log usage
OBSERVED_STALE_DAYS = 31     # externally-dependent rule re-verify window
DECISION_LOG_ARCHIVE_WORDS = 12000
DECISION_LINE_WORDS = 30     # one-line decision format cap; WARN only
RECORDS_SPLIT_WORDS = 10000  # per-stream split trigger for a records file
REFERENCE_STALE_DAYS = 90    # references/*.md archive-candidate age
LESSON_ENTRY_WORDS = 150     # per-entry cap in governance/lessons.md ## Entries

# word budgets by doc, exact path first, then class rules
BUDGET_EXACT = {
    "AIOS.md": 2000,
    "wiki/CLAUDE.md": 2000,
    "wiki/rules.md": 400,
    "README.md": 800,
    "operations.md": 3200,
    "governance/repo-contract.md": 900,
    "governance/gating.md": 1150,
    "governance/routing.md": 1000,
    "governance/building.md": 750,
    "governance/satellite-repos.md": 700,
    "governance/lessons.md": 2000,       # capped domain-less catch-all
    "governance/memory-promotion.md": 1000,  # capture-to-promote pipeline policy
    "governance/design-rubric.md": 700,      # UI/design readability rubric
}
BUDGET_SATELLITE_CLAUDE = 1200  # a satellite CLAUDE.md is a map
BUDGET_SKILL = 500           # any skills/*/SKILL.md
BUDGET_SKILL_REF = 700       # skill references/*-rules.md (terse rules files)
BUDGET_RULE = 500            # any other governance/*.md
BUDGET_REFERENCE = 700       # references/*.md (top-level lookup docs)

STRAY_SUFFIXES = (".bak", ".orig", ".swp", "~")
SKIP_DIRS = {".git", "node_modules", "__pycache__"}
WIKI_PREFIXES = ("wiki/entities/", "wiki/concepts/", "wiki/synthesis/",
                 "wiki/confidential/", "wiki/sources/", "wiki/metadata/",
                 "wiki/annex/", "wiki/raw/")

# ---- config: wiki health ----------------------------------------------------

WIKI_PAGE_BUDGET = 2000      # living page word cap (schema Rule 1)
TRUTH_WORD_CAP = 250         # words in a `# Current truth` section body
TRUTH_STALE_DAYS = 31        # newest evidence newer than `updated:` by this
UNDISTILLED_DAYS = 14        # empty `distilled:` backlog age
UNMINTED_PAGES = 3           # distinct pages naming a target with no page

LIVING_DIRS = ("entities", "concepts", "synthesis", "confidential")
ORPHAN_DIRS = ("entities", "concepts", "synthesis")
NO_UPDATES_LINE = "(No durable updates.)"

# taxonomy: what may live at each contract point
RECORDS_ALLOWED = {
    "decisions.md", "decisions_history", "sessions_index.md",
    "brainstorms", "reports", "README.md", ".sessions_index.lock", ".gitkeep",
}
DATED_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")
CLAUDE_MACHINERY_FILES = {
    "settings.json", "settings.local.json", "launch.json", "mcp.json",
    ".gitignore", ".DS_Store",
}
PRODUCT_VOCAB = {"src", "server", "shared", "scripts", "test", "spec", "docs",
                 "dist"}
PLURAL_VARIANTS = {"tests", "specs", "srcs"}
PRODUCT_ROOT_MD = {"README.md", "CHANGELOG.md", "LICENSE.md", "NOTICE.md",
                   "CLAUDE.md", "AGENTS.md"}
HUB_ROOT_MD = {"AIOS.md", "CLAUDE.md", "AGENTS.md", "GEMINI.md", "README.md",
               "operations.md", "LICENSE.md", "NOTICE.md"}
TEST_FILE_RE = re.compile(r"\.test\.[A-Za-z0-9]+$")

ROOT = os.path.abspath(os.getcwd())
TODAY = date.today()

findings = []  # (severity, tag, group, message, path)


def add(sev, tag, group, message, path=""):
    findings.append((sev, tag, group, message, path))


def rel(p):
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:
        return p


def days_since_mtime(p):
    try:
        return (datetime.now() - datetime.fromtimestamp(os.path.getmtime(p))).days
    except OSError:
        return None


def read_text(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def wordcount(p):
    text = read_text(p)
    return None if text is None else len(text.split())


def git(*args):
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                             text=True, timeout=15)
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _git_remote(path):
    try:
        out = subprocess.run(["git", "-C", path, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def walk_files():
    """Yield absolute paths of tracked-ish files, skipping heavy/ignored dirs
    and symlinks (so the canonical floor file is counted once)."""
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if os.path.join("wiki", "raw", "transcripts") in dirpath:
            continue
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            yield full


def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


# ---- group 1: filesystem cruft ---------------------------------------------

def check_filesystem():
    for p in walk_files():
        base = os.path.basename(p)
        if base == ".DS_Store" or base.endswith(STRAY_SUFFIXES):
            add("MED", "auto-safe", "filesystem", f"stray file {base}", rel(p))

    tmp = os.path.join(ROOT, ".tmp")
    if os.path.isdir(tmp):
        ages = [days_since_mtime(os.path.join(dp, f))
                for dp, _, fs in os.walk(tmp) for f in fs]
        ages = [a for a in ages if a is not None]
        if ages and min(ages) > THRESHOLD_DAYS:
            add("MED", "judgment", "filesystem",
                f".tmp/ scratch untouched {min(ages)}d, clear it?", ".tmp")

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if not dirnames and not filenames:
            add("LOW", "judgment", "filesystem", "empty directory", rel(dirpath))


# ---- group 2: git hygiene ---------------------------------------------------

def check_git():
    if git("rev-parse", "--is-inside-work-tree") != "true":
        return

    url = git("remote", "get-url", "origin")
    if url and APPROVED_REMOTE_OWNER and "github.com" in url \
            and APPROVED_REMOTE_OWNER not in url:
        add("HIGH", "judgment", "git",
            f"origin remote is not the approved personal repo: {url}", "")

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch and branch not in ("main", "HEAD"):
        add("LOW", "judgment", "git", f"working on branch '{branch}', not main", "")

    porcelain = git("status", "--porcelain")
    if porcelain:
        for line in porcelain.splitlines():
            code, _, name = line.partition(" ")
            path = name.strip().strip('"')
            full = os.path.join(ROOT, path)
            age = days_since_mtime(full)
            if line.startswith("??"):
                add("MED", "judgment", "git", "untracked, ignore or commit?", path)
            elif age is not None and age > THRESHOLD_DAYS:
                add("MED", "judgment", "git", f"modified, uncommitted {age}d", path)

    upstream = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream:
        ahead = git("rev-list", "--count", "@{u}..HEAD")
        if ahead and ahead.isdigit() and int(ahead) > 0:
            add("MED", "judgment", "git",
                f"{ahead} local commit(s) not pushed to {upstream}", "")


# ---- group 3: freshness / staleness ----------------------------------------

def check_freshness():
    ledger = os.path.join(ROOT, "records", "sessions_index.md")
    text = read_text(ledger)
    if text:
        pending = sum(1 for ln in text.splitlines() if "(pending)" in ln)
        if pending:
            add("LOW", "judgment", "freshness",
                f"{pending} session-ledger row(s) still '(pending)'", rel(ledger))

    prio = os.path.join(ROOT, "context", "priorities.md")
    age = _dated_field_age(prio, r"Last refreshed:\**\s*(\d{4}-\d{2}-\d{2})")
    if age is not None and age > LIVE_DOC_STALE_DAYS:
        add("MED", "judgment", "freshness",
            f"priorities.md live heading is {age}d old, refresh?", rel(prio))

    _check_broken_links()


def _dated_field_age(path, pattern):
    text = read_text(path)
    if text is None:
        return None
    m = re.search(pattern, text)
    if not m:
        return None
    d = parse_date(m.group(1))
    if d is None:
        return None
    return (TODAY - d).days


LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
OP_DOC_DIRS = (".claude", "context", "references", "plans", "governance")


def _check_broken_links():
    for p in walk_files():
        r = rel(p)
        if not r.endswith(".md"):
            continue
        if not (r.startswith(OP_DOC_DIRS) or "/" not in r):
            continue
        text = read_text(p)
        if text is None:
            continue
        for target in LINK_RE.findall(text):
            link = target.split("#")[0].strip()
            if not link or link.startswith(("http://", "https://", "mailto:")):
                continue
            if link.startswith(("/", "~")):
                continue
            dest = os.path.normpath(os.path.join(os.path.dirname(p), link))
            if not os.path.exists(dest):
                add("LOW", "judgment", "freshness",
                    f"broken relative link -> {link}", r)


# ---- group 4: operating-doc health -----------------------------------------

def check_docs():
    for p in walk_files():
        r = rel(p)
        if not r.endswith(".md"):
            continue
        if r.startswith(WIKI_PREFIXES):
            continue  # wiki content is the wiki-health group's job
        budget = _budget_for(r)
        if budget is None:
            continue
        wc = wordcount(p)
        if wc is not None and wc > budget:
            add("MED", "judgment", "doc-health",
                f"over budget: {wc}w > {budget}w", r)

    _check_decision_log()
    _check_lessons_file()
    _check_observed_dates()
    _check_satellites()
    _check_records_split()


def _budget_for(r):
    if r in BUDGET_EXACT:
        return BUDGET_EXACT[r]
    if r.startswith("skills/") and r.endswith("/SKILL.md"):
        return BUDGET_SKILL
    if r.startswith("skills/") and "/references/" in r:
        # only terse *-rules.md files are capped; procedural references
        # (walkthroughs, rubrics) are uncapped lookup material
        return BUDGET_SKILL_REF if r.endswith("-rules.md") else None
    if r.startswith("governance/"):
        return BUDGET_RULE
    if r.startswith("references/templates/"):
        return None
    if r.startswith("references/"):
        return BUDGET_REFERENCE
    return None


DECISION_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2}):\s*(.*)$")
DECISION_HEADER_OK_RE = re.compile(
    r"\(session\s+[0-9a-f]{4,}…?,\s*stream:\s*[\w-]+\)\s*$")


def _check_decision_log():
    log = os.path.join(ROOT, "records", "decisions.md")
    text = read_text(log)
    if text is None:
        return
    wc = len(text.split())
    if wc > DECISION_LOG_ARCHIVE_WORDS:
        add("LOW", "judgment", "doc-health",
            f"decisions log large ({wc}w), rotate old months to "
            "decisions_history/", rel(log))

    for line in text.splitlines():
        m = DECISION_HEADER_RE.match(line)
        if m and not DECISION_HEADER_OK_RE.search(line):
            add("MED", "judgment", "doc-health",
                "decisions block header missing (session <id>, stream: <name>): "
                f"{m.group(2)[:50]}", rel(log))
        s = line.strip()
        if s.startswith("- **") and len(s.split()) > DECISION_LINE_WORDS:
            add("MED", "judgment", "doc-health",
                f"decision line over budget ({len(s.split())}w > "
                f"{DECISION_LINE_WORDS}w): {s[:55]}...", rel(log))


def _check_lessons_file():
    """Each ### entry under governance/lessons.md's ## Entries section is
    <=150 words and carries a provenance link. Policy prose above ## Entries is
    never an entry, so it is never flagged."""
    path = os.path.join(ROOT, "governance", "lessons.md")
    text = read_text(path)
    if text is None:
        return
    # the ## Entries span: from that heading to the next h1/h2, keeping ### entries
    m = re.search(r"(?m)^##\s+Entries\s*$", text)
    if not m:
        return
    rest = text[m.end():]
    nxt = re.search(r"(?m)^#{1,2} ", rest)
    entries_body = rest[:nxt.start()] if nxt else rest
    if not entries_body.strip():
        return
    # split into ### blocks; the text before the first ### is not an entry
    parts = re.split(r"(?m)^###\s+(.+)$", entries_body)
    # parts = [pre, head1, body1, head2, body2, ...]
    for i in range(1, len(parts), 2):
        head = parts[i].strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        wc = len(body.split())
        if wc > LESSON_ENTRY_WORDS:
            add("MED", "judgment", "doc-health",
                f"lesson entry over budget ({wc}w > {LESSON_ENTRY_WORDS}w): "
                f"{head[:50]}", "governance/lessons.md")
        if not LINK_RE.search(body):
            add("MED", "judgment", "doc-health",
                f"lesson entry missing a provenance link: {head[:50]}",
                "governance/lessons.md")


OBSERVED_RE = re.compile(r"observed\s+(\d{4})-(\d{2})", re.IGNORECASE)


def _check_observed_dates():
    """Rules that depend on external behavior carry an `observed YYYY-MM` stamp;
    old stamps mean re-verify before trusting."""
    for p in walk_files():
        r = rel(p)
        if not r.endswith(".md"):
            continue
        if not (r.startswith((".claude", "references", "skills"))
                or r == "operations.md"):
            continue
        text = read_text(p)
        if text is None:
            continue
        for y, m in OBSERVED_RE.findall(text):
            try:
                d = date(int(y), int(m), 1)
            except ValueError:
                continue
            if (TODAY - d).days > OBSERVED_STALE_DAYS:
                add("LOW", "judgment", "doc-health",
                    f"externally-dependent rule (observed {y}-{m}), reverify", r)


def _parse_md_table(section_text):
    header, rows = None, []
    for line in section_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(set(c) <= set("-: ") for c in cells):
            continue
        if header is None:
            header = cells
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _check_satellites():
    """Validate operations.md ## Satellites rows against the filesystem: repo
    path exists, git origin matches the table, CLAUDE.md present. Silent when
    the registry is empty (the shipped default)."""
    text = read_text(os.path.join(ROOT, "operations.md"))
    if text is None:
        return
    for row in _parse_md_table(section(text, "## Satellites")):
        name = row.get("Satellite", "?")
        raw = row.get("Repo path", "").strip().strip("`")
        repo_path = os.path.expanduser(raw) if raw else ""
        if not repo_path or not os.path.isdir(repo_path):
            add("HIGH", "judgment", "doc-health",
                f"satellite '{name}' repo path does not exist: {raw or '(empty)'}",
                "operations.md")
            continue
        m = re.search(r"[\w.-]+/[\w.-]+", row.get("Remote", "").strip().strip("`"))
        slug = m.group(0) if m else ""
        actual = _git_remote(repo_path)
        if slug and actual and slug not in actual:
            add("HIGH", "judgment", "doc-health",
                f"satellite '{name}' remote mismatch: table says {slug}, "
                f"origin is {actual}", "operations.md")
        if not os.path.exists(os.path.join(repo_path, "CLAUDE.md")):
            add("MED", "judgment", "doc-health",
                f"satellite '{name}' has no CLAUDE.md floor", "operations.md")


def _check_records_split():
    rec = os.path.join(ROOT, "records")
    if not os.path.isdir(rec):
        return
    for name in sorted(os.listdir(rec)):
        if not name.endswith(".md"):
            continue
        wc = wordcount(os.path.join(rec, name))
        if wc and wc > RECORDS_SPLIT_WORDS:
            add("INFO", "judgment", "doc-health",
                f"records file at {wc}w > ~{RECORDS_SPLIT_WORDS}w, "
                "per-stream split trigger", f"records/{name}")


# ---- group 5: structural loose ends ----------------------------------------

TODO_RE = re.compile(r"\b(TODO|FIXME|XXX)\b\s*:")


def _disp(root):
    if root == ROOT:
        return ""
    home = os.path.expanduser("~")
    return (root.replace(home, "~") if root.startswith(home) else root) + "/"


def _satellite_roots():
    text = read_text(os.path.join(ROOT, "operations.md"))
    if text is None:
        return []
    out = []
    for row in _parse_md_table(section(text, "## Satellites")):
        raw = row.get("Repo path", "").strip().strip("`")
        p = os.path.expanduser(raw) if raw else ""
        if p and os.path.isdir(p):
            out.append((row.get("Satellite", "?"), p))
    return out


def check_structural():
    for p in walk_files():
        r = rel(p)
        if not r.endswith(".md"):
            continue
        if not r.startswith(("skills/", "governance/")) and r != "AIOS.md":
            continue
        text = read_text(p)
        if text is None:
            continue
        for i, ln in enumerate(text.splitlines(), 1):
            m = TODO_RE.search(ln)
            if m:
                add("LOW", "judgment", "structural",
                    f"{m.group(1)} marker at line {i}", r)
                break

    check_taxonomy()
    _check_references_staleness()


def check_taxonomy():
    """The repo-contract, enforced across the hub and every registered
    satellite: records/ = the 4 streams only (hub), no records/ in satellites,
    .claude/ machinery-only, graphify-out always a symlink, plans/ dated,
    vocabulary + root allowlists, tests unified."""
    rec = os.path.join(ROOT, "records")
    if os.path.isdir(rec):
        for name in sorted(os.listdir(rec)):
            if name in RECORDS_ALLOWED:
                continue
            add("MED", "judgment", "structural",
                f"records/{name} is not one of the 4 allowed streams "
                "(decisions, sessions_index, brainstorms, reports)",
                f"records/{name}")

    for label, root in [("hub", ROOT)] + _satellite_roots():
        _check_claude_machinery_only(label, root)
        _check_graphify_symlink(label, root)
        _check_plans_dated(label, root)
        _check_vocabulary(label, root)
        _check_root_allowlist(label, root)
        if label != "hub":
            _check_no_satellite_records(label, root)
            _check_test_layout(label, root)
            _check_satellite_claude_budget(label, root)
            _check_agents_parity(label, root)


def _check_claude_machinery_only(label, root):
    cdir = os.path.join(root, ".claude")
    if not os.path.isdir(cdir):
        return
    for name in sorted(os.listdir(cdir)):
        full = os.path.join(cdir, name)
        if os.path.isdir(full) or os.path.islink(full):
            continue
        if name in CLAUDE_MACHINERY_FILES or name.startswith("."):
            continue
        add("MED", "judgment", "structural",
            f"[{label}] .claude/{name} is knowledge, not harness machinery; "
            "move it to docs/ (publishable) or the hub project folder (private)",
            f"{_disp(root)}.claude/{name}")


def _check_graphify_symlink(label, root):
    g = os.path.join(root, "graphify-out")
    if os.path.exists(g) and not os.path.islink(g):
        add("MED", "judgment", "structural",
            f"[{label}] graphify-out is a real directory; it must be a symlink "
            "into the hub graphs/", f"{_disp(root)}graphify-out")


def _check_plans_dated(label, root):
    if label != "hub":
        return
    d = os.path.join(root, "plans")
    if not os.path.isdir(d):
        return
    bad = [name for name in sorted(os.listdir(d))
           if name.endswith(".md") and name != "README.md"
           and not DATED_NAME_RE.match(name)
           and os.path.isfile(os.path.join(d, name))]
    if bad:
        shown = ", ".join(bad[:6]) + (" ..." if len(bad) > 6 else "")
        add("INFO", "judgment", "structural",
            f"[{label}] {len(bad)} plans/ file(s) lack a YYYY-MM-DD- prefix: "
            f"{shown}", f"{_disp(root)}plans/")


def _repo_claude_text(root):
    for name in ("AIOS.md", "CLAUDE.md", "AGENTS.md"):
        t = read_text(os.path.join(root, name))
        if t:
            return t
    return ""


def _git_ignored(root, relpath):
    try:
        out = subprocess.run(["git", "-C", root, "check-ignore", "-q", relpath],
                             capture_output=True, timeout=10)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _top_dirs(root):
    for name in sorted(os.listdir(root)):
        full = os.path.join(root, name)
        if not os.path.isdir(full) or os.path.islink(full):
            continue
        if name.startswith(".") or name in SKIP_DIRS:
            continue
        if _git_ignored(root, name):
            continue
        yield name, full


def _check_vocabulary(label, root):
    """Top-level dirs come from the fixed product vocabulary or are named in
    the repo's floor file. Plural variants are always a finding. The hub's own
    folders are all named in AIOS.md, so they pass the floor clause."""
    claude = _repo_claude_text(root)
    for name, _ in _top_dirs(root):
        if name in PLURAL_VARIANTS:
            singular = name[:-1] if name.endswith("s") else name
            add("MED", "judgment", "structural",
                f"[{label}] top-level {name}/ is a plural variant; the "
                f"vocabulary is singular ({singular}/)", f"{_disp(root)}{name}")
            continue
        base = "dist" if name.startswith("dist") else name
        if base in PRODUCT_VOCAB:
            continue
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", claude):
            continue
        add("MED", "judgment", "structural",
            f"[{label}] top-level {name}/ is not in the repo vocabulary and is "
            "not named in the floor file (repo-contract.md)",
            f"{_disp(root)}{name}")


def _check_root_allowlist(label, root):
    allowed = HUB_ROOT_MD if label == "hub" else PRODUCT_ROOT_MD
    for name in sorted(os.listdir(root)):
        if not name.endswith(".md"):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        if name in allowed:
            continue
        kind = "hub" if label == "hub" else "product"
        add("MED", "judgment", "structural",
            f"[{label}] root markdown {name} is not in the {kind} root "
            "allowlist (repo-contract.md)", f"{_disp(root)}{name}")


def _check_test_layout(label, root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".")
            and not _git_ignored(root, os.path.relpath(os.path.join(dirpath, d),
                                                        root))]
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == "test" or rel_dir.startswith("test" + os.sep):
            dirnames[:] = []
            continue
        for d in list(dirnames):
            if d == "__tests__":
                r = os.path.relpath(os.path.join(dirpath, d), root)
                add("MED", "judgment", "structural",
                    f"[{label}] {r} lives outside top-level test/ "
                    "(repo-contract.md)", f"{_disp(root)}{r}")
        for name in filenames:
            if TEST_FILE_RE.search(name):
                r = os.path.relpath(os.path.join(dirpath, name), root)
                add("MED", "judgment", "structural",
                    f"[{label}] test file {r} lives outside top-level test/ "
                    "(repo-contract.md)", f"{_disp(root)}{r}")


def _check_references_staleness():
    """A hub references/*.md untouched > 90d with zero citations anywhere in
    the repo is an archive candidate. Never auto-moved: confirm-to-fix."""
    refdir = os.path.join(ROOT, "references")
    if not os.path.isdir(refdir):
        return
    for name in sorted(os.listdir(refdir)):
        p = os.path.join(refdir, name)
        if not name.endswith(".md") or not os.path.isfile(p):
            continue
        age = days_since_mtime(p)
        if age is None or age <= REFERENCE_STALE_DAYS:
            continue
        out = git("grep", "-l", "-F", name) or ""
        if [h for h in out.splitlines() if h and h != f"references/{name}"]:
            continue
        add("INFO", "judgment", "structural",
            f"references/{name} untouched {age}d and uncited across the repo; "
            "archive candidate (confirm-to-fix, never auto-moved)",
            f"references/{name}")


def _check_no_satellite_records(label, root):
    if os.path.isdir(os.path.join(root, "records")):
        add("MED", "judgment", "structural",
            f"[{label}] satellite has its own records/; the streams live in "
            "the hub only (fold in, then delete)", f"{_disp(root)}records/")


def _check_satellite_claude_budget(label, root):
    p = os.path.join(root, "CLAUDE.md")
    if not os.path.exists(p):
        return
    wc = wordcount(p)
    if wc is not None and wc > BUDGET_SATELLITE_CLAUDE:
        add("MED", "judgment", "structural",
            f"[{label}] CLAUDE.md over budget: {wc}w > {BUDGET_SATELLITE_CLAUDE}w "
            "(repo-contract.md: the floor is a map)", f"{_disp(root)}CLAUDE.md")


def _agents_parity(root):
    claude = os.path.join(root, "CLAUDE.md")
    agents = os.path.join(root, "AGENTS.md")
    if not os.path.exists(agents) or not os.path.exists(claude):
        return False
    try:
        if os.path.realpath(agents) == os.path.realpath(claude):
            return True
    except OSError:
        pass
    a, c = read_text(agents), read_text(claude)
    return a is not None and a == c


def _check_agents_parity(label, root):
    if not _agents_parity(root):
        add("MED", "judgment", "structural",
            f"[{label}] AGENTS.md floor missing or out of parity with CLAUDE.md "
            "(repo-contract.md)", f"{_disp(root)}AGENTS.md")


# ---- group 6: wiki health ---------------------------------------------------

WIKILINK_RE = re.compile(r"\[\[([^\]\[|#]+)(?:#[^\]\[|]*)?(?:\|[^\]\[]*)?\]\]")
FM_LIST_RE = re.compile(r"^\[(.*)\]$")
LINK_PLACEHOLDERS = {"page", "source_page", "slug", "wikilink", "wikilinks",
                     "note name", "entity", "concept", "target", "source",
                     "name"}


def wiki_root():
    return os.path.join(ROOT, "wiki")


def wiki_pages():
    out = []
    w = wiki_root()
    if not os.path.isdir(w):
        return out
    for dirpath, dirnames, filenames in os.walk(w):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and d != "raw"]
        for name in filenames:
            if not name.endswith(".md"):
                continue
            full = os.path.join(dirpath, name)
            key = os.path.relpath(full, w)[:-3]
            out.append((key.replace(os.sep, "/"), full))
    return out


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        key, sep, value = line.partition(":")
        if sep:
            fm[key.strip()] = value.strip()
    return fm


def fm_list(value):
    if not value:
        return []
    m = FM_LIST_RE.match(value.strip())
    inner = m.group(1) if m else value
    return [v.strip() for v in inner.split(",") if v.strip()]


def section(text, heading):
    pattern = re.compile(r"(?m)^%s[^\n]*\n" % re.escape(heading))
    m = pattern.search(text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"(?m)^#{1,6} ", rest)
    return rest[:nxt.start()] if nxt else rest


def check_wiki():
    if not os.path.isdir(wiki_root()):
        return
    pages = wiki_pages()
    texts = {}
    for key, full in pages:
        t = read_text(full)
        if t is not None:
            texts[key] = t
    if not texts:
        return
    _wiki_links_checks(texts)
    _wiki_page_checks(texts)
    _wiki_ingest_gaps(texts)
    _wiki_sources_checks(texts)
    _wiki_tag_sprawl(texts)


def _wiki_links_checks(texts):
    links = {key: {t.strip() for t in WIKILINK_RE.findall(text) if t.strip()}
             for key, text in texts.items()}
    known_slugs = defaultdict(set)
    for key in texts:
        known_slugs[key.split("/")[-1]].add(key)

    # orphans
    for key in sorted(texts):
        if not key.startswith(tuple(d + "/" for d in ORPHAN_DIRS)):
            continue
        slug = key.split("/")[-1]
        inbound = sum(1 for other, targets in links.items()
                      if other != key and (slug in targets or key in targets))
        if inbound == 0:
            add("MED", "judgment", "wiki-health",
                "orphan page: no inbound [[wikilink]] from any wiki page",
                f"wiki/{key}.md")

    # unminted mentions
    breadth = defaultdict(set)
    for key, targets in links.items():
        for t in targets:
            breadth[t].add(key)
    for target in sorted(breadth):
        bare = target.split("/")[-1]
        if bare.lower() in LINK_PLACEHOLDERS:
            continue
        if target in texts or bare in known_slugs:
            continue
        if len(breadth[target]) >= UNMINTED_PAGES:
            add("MED", "judgment", "wiki-health",
                f"[[{target}]] named on {len(breadth[target])} pages with no "
                "page, stub candidate", "wiki/")


def _wiki_page_checks(texts):
    for key in sorted(texts):
        if not key.startswith(tuple(d + "/" for d in LIVING_DIRS)):
            continue
        text = texts[key]
        path = f"wiki/{key}.md"
        fm = frontmatter(text)
        evidence = section(text, "# Evidence")
        truth = section(text, "# Current truth")

        total = len(text.split())
        if total > WIKI_PAGE_BUDGET:
            add("MED", "judgment", "wiki-health",
                f"living page over budget: {total}w > {WIKI_PAGE_BUDGET}w, "
                "archival candidate (annex rotation)", path)

        truth_words = len(truth.split())
        if truth_words > TRUTH_WORD_CAP:
            add("LOW", "judgment", "wiki-health",
                f"# Current truth is {truth_words}w (cap {TRUTH_WORD_CAP}w), "
                "trim or demote to Evidence", path)

        ev_dates = [d for d in (parse_date(m) for m in
                                re.findall(r"(?m)^- (\d{4}-\d{2}-\d{2})", evidence))
                    if d]
        updated = parse_date(fm.get("updated", ""))
        if ev_dates and updated:
            lag = (max(ev_dates) - updated).days
            if lag > TRUTH_STALE_DAYS:
                add("MED", "judgment", "wiki-health",
                    f"evidence runs {lag}d past `updated:`, truth not "
                    "re-promoted", path)


def _wiki_ingest_gaps(texts):
    """Raw files with no source page, and source pages whose named raw files
    are gone. Transcripts are gitignored, so absent locally is not a gap."""
    trans = os.path.join(wiki_root(), "raw", "transcripts")
    raw_names = []
    if os.path.isdir(trans):
        raw_names = [n for n in sorted(os.listdir(trans))
                     if n.endswith(".md") and n != ".gitkeep"]
    for name in raw_names:
        slug = name[:-3]
        if f"sources/{slug}" not in texts:
            add("MED", "judgment", "wiki-health",
                f"raw transcript has no source page (expected "
                f"wiki/sources/{slug}.md)", f"wiki/raw/transcripts/{name}")

    if not raw_names:
        return
    for key in sorted(texts):
        if not key.startswith("sources/"):
            continue
        origin = frontmatter(texts[key]).get("origin", "")
        for named in re.findall(r"raw/[\w./-]+\.md", origin):
            if not os.path.exists(os.path.join(wiki_root(), named)):
                add("MED", "judgment", "wiki-health",
                    f"source page names a missing raw file: {named}",
                    f"wiki/{key}.md")


def _wiki_sources_checks(texts):
    """Undistilled backlog."""
    for key in sorted(texts):
        if not key.startswith("sources/"):
            continue
        fm = frontmatter(texts[key])
        if fm.get("distilled", ""):
            continue
        slug = key.split("/")[-1]
        m = re.match(r"(\d{4}-\d{2}-\d{2})", slug)
        born = parse_date(m.group(1)) if m else parse_date(fm.get("created", ""))
        if born and (TODAY - born).days > UNDISTILLED_DAYS:
            add("MED", "judgment", "wiki-health",
                f"undistilled {(TODAY - born).days}d (empty `distilled:`)",
                f"wiki/{key}.md")


def _registered_tags():
    tags = set()
    text = read_text(os.path.join(wiki_root(), "metadata", "tag_registry.md"))
    if text:
        for line in text.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or not cells[0] or set(cells[0]) <= set("-: "):
                continue
            if cells[0].lower() in ("slug", "canonical"):
                continue
            slug = cells[0].removeprefix("(example)").strip()
            tags.add(slug.lower())
            if len(cells) >= 3:
                tags.update(a.strip().lower() for a in cells[2].split(",")
                            if a.strip())
    return tags


def _wiki_tag_sprawl(texts):
    registered = _registered_tags()
    if not registered:
        return
    usage = defaultdict(set)
    for key, text in texts.items():
        if key.startswith("metadata/"):
            continue
        for tag in fm_list(frontmatter(text).get("tags", "")):
            usage[tag.lower()].add(key)
    for tag in sorted(usage):
        if tag not in registered:
            add("MED", "judgment", "wiki-health",
                f"tag '{tag}' used on {len(usage[tag])} page(s) but absent "
                "from the tag registry", "wiki/metadata/tag_registry.md")


# ---- group 7: ticket tracker (config seam, off by default) ------------------

def check_ticket_tracker():
    """Tracker-drift checks run only when NISSE_TRACKER_DRIFT=1 and your own
    scripts/ticket_tracker.py integration exists. Off by default: the skeleton
    works fully without a tracker."""
    if not TRACKER_DRIFT:
        return
    mod = os.path.join(ROOT, "scripts", "ticket_tracker.py")
    if not os.path.exists(mod):
        add("LOW", "judgment", "ticket_tracker",
            "NISSE_TRACKER_DRIFT=1 but scripts/ticket_tracker.py does not "
            "exist; wire the connector first (operations.md Connectors)",
            "scripts/ticket_tracker.py")
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import ticket_tracker as tt
        result = tt.check(root=ROOT)
    except Exception as e:
        add("LOW", "judgment", "ticket_tracker",
            f"tracker checks unavailable ({e.__class__.__name__}: {e})",
            "scripts/ticket_tracker.py")
        return
    for f in result.findings:
        add(f.severity, f.tag, "ticket_tracker", f.message, f.path)


# ---- output -----------------------------------------------------------------

GROUP_ORDER = ["filesystem", "git", "freshness", "doc-health", "structural",
               "wiki-health", "ticket_tracker"]
GROUP_TITLE = {
    "filesystem": "1. Filesystem cruft",
    "git": "2. Git hygiene",
    "freshness": "3. Freshness / staleness",
    "doc-health": "4. Operating-doc health",
    "structural": "5. Structural loose ends",
    "wiki-health": "6. Wiki health (mechanical)",
    "ticket_tracker": "7. Ticket tracker (off unless wired)",
}
SEV_RANK = {"HIGH": 0, "MED": 1, "LOW": 2, "INFO": 3}

CHECKS = (check_filesystem, check_git, check_freshness, check_docs,
          check_structural, check_wiki, check_ticket_tracker)


def run_checks(root=None, checks=None):
    global ROOT, findings
    ROOT = os.path.abspath(root or os.environ.get("HYGIENE_ROOT") or os.getcwd())
    findings = []
    for fn in (CHECKS if checks is None else checks):
        try:
            fn()
        except Exception as e:  # a broken check must not kill the scan
            add("LOW", "judgment", "structural",
                f"scan check {fn.__name__} errored: {e}", "")
    return findings


def main(root=None):
    results = run_checks(root)

    print(f"# Workspace hygiene scan, {TODAY.isoformat()}")
    print(f"# root: {ROOT}")
    auto = sum(1 for f in results if f[1] == "auto-safe")
    judg = sum(1 for f in results if f[1] == "judgment")
    print(f"# {len(results)} finding(s): {auto} auto-safe, {judg} judgment\n")

    if not results:
        print("clean, nothing to report.")
        return 0

    for g in GROUP_ORDER:
        group_items = [f for f in results if f[2] == g]
        if not group_items:
            continue
        group_items.sort(key=lambda f: (SEV_RANK.get(f[0], 9), f[1], f[4], f[3]))
        print(f"## {GROUP_TITLE[g]}")
        for sev, tag, _, msg, path in group_items:
            loc = f"  [{path}]" if path else ""
            print(f"[{sev}][{tag}] {msg}{loc}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
