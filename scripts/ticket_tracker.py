#!/usr/bin/env python3
"""Tracker-drift connector (tier 2, bring-your-own-key): enforces
governance/ticket-tracker.md against a real board.

Deterministic: Linear GraphQL issues/comments/history + git log +
records/sessions_index.md + records/decisions.md + filesystem. No LLM.
Stdlib only. Off by default: `scripts/hygiene_check.py` only imports this
module when NISSE_TRACKER_DRIFT=1 (see its group-7 check).

Ships wired to Linear because that's the concrete example provider, but the
check/sweep logic itself is tracker-agnostic: swap LinearClient for your own
tracker's client and everything downstream (run_checks, sweep, the hygiene
hook) keeps working, as long as it produces the same issue shape (see
ISSUES_QUERY below for the fields the checks read).

Two modes:
  --check   read-only, print findings (what the hygiene group-7 hook imports)
  --sweep   apply auto-fixes within the sweep authority, emit the ping payload
            (--dry-run makes --sweep side-effect-free: fetch is read-only, no
             tracker mutation, no ping send, real cursor untouched)

Sweep authority (the contract, governance/ticket-tracker.md): auto-fix ONLY
the two evidence-provable enum flips (commit-referenced Backlog/Todo ->
In Progress; parent In Review with unstarted children -> In Progress).
Canceled, Done, and archive are propose-only. Never edits descriptions or
comments.

Config (env vars, all in .env.example):
  LINEAR_API_KEY              required for any real fetch/mutation.
  TICKET_TRACKER_PROJECTS     comma-separated board/project names to track.
                               Unset = the script refuses to fetch (nothing
                               to track yet); wire it once you have a board.
  TICKET_TRACKER_KEY_PREFIX   your tracker's issue-ID prefix (the "PROJ" in
                               "PROJ-123"). Default "PROJ": a placeholder,
                               almost certainly wrong for your workspace.
  TICKET_TRACKER_OWNER_EMAIL  the owner's tracker account email, used only by
                               the "unaddressed owner comment" check. Unset =
                               that one check never fires; everything else
                               still runs.
  TICKET_TRACKER_STALE_DAYS       default 7 (contract).
  TICKET_TRACKER_BACKPRESSURE_CAP default 5 (contract).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections import namedtuple
from datetime import date, datetime, timedelta

# ---- config -----------------------------------------------------------------

_PROJECTS_RAW = os.environ.get("TICKET_TRACKER_PROJECTS", "")
PROJECTS = [p.strip() for p in _PROJECTS_RAW.split(",") if p.strip()]

TICKET_PREFIX = os.environ.get("TICKET_TRACKER_KEY_PREFIX", "PROJ")
OWNER_EMAIL = os.environ.get("TICKET_TRACKER_OWNER_EMAIL", "").lower()

STALE_DAYS = int(os.environ.get("TICKET_TRACKER_STALE_DAYS", "7"))
BACKPRESSURE_CAP = int(os.environ.get("TICKET_TRACKER_BACKPRESSURE_CAP", "5"))

STATE_PATH = ".tmp/tracker_drift/state.json"
PING_PATH = ".tmp/tracker_drift/ping.md"

LINEAR_URL = "https://api.linear.app/graphql"

_PREFIX_ESC = re.escape(TICKET_PREFIX)
TICKET_RE = re.compile(rf"\b{_PREFIX_ESC}-\d+\b")
# Check (a) evidence: the ticket must LEAD a commit subject ("PROJ-124: ...",
# "PROJ-125 plan draft: ..."), the work-commit convention. A mid-subject or
# body mention ("records: decision blocks for PROJ-111") is board/records
# work ABOUT the ticket, not work ON it.
SUBJECT_REF_RE = re.compile(rf"^({_PREFIX_ESC}-\d+)\b", re.MULTILINE)
# repo-relative paths in descriptions; conservative: must contain a slash
FILE_RE = re.compile(r"\b((?:[\w.-]+/)+[\w.-]+\.(?:py|md|json|ya?ml|sh|ts|tsx|js))\b")
CHECKBOX_DONE_RE = re.compile(r"^\s*[-*]\s*\[x\]", re.IGNORECASE | re.MULTILINE)
CHECKBOX_OPEN_RE = re.compile(r"^\s*[-*]\s*\[ \]", re.MULTILINE)
DECISION_HEADER_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2}):", re.MULTILINE)
# Tracker writes under a personal API key carry the owner's account identity
# even when an agent made them. Tracker governance requires agent
# claim/handoff/completion comments to carry a session marker, so those
# durable markers are the attribution seam. Agent names below (codex, claude)
# are generic AI-agent labels, not tied to any specific vendor account.
AGENT_COMMENT_RE = re.compile(
    r"(?:\bbatch-run-\d+\b|"
    r"^\s*(?:handoff(?:\s+resolved)?\s*[:,]|"
    r"landed-main\s+closeout\b|completion\s+note\s*[:(])|"
    r"\b(?:codex|claude)\s+handoff\b|"
    r"\bclaimed\s+by\s+(?:codex|claude)\b|"
    r"\bsession(?:\s+id)?\s*[:(]?\s*[0-9a-f]{8,}\b)",
    re.IGNORECASE | re.MULTILINE,
)

Finding = namedtuple("Finding", "severity tag group message path")
CheckResult = namedtuple("CheckResult", "findings fixes signoff_queue")


class ConfigError(Exception):
    pass


# ---- Linear client (the example provider) -----------------------------------

ISSUES_QUERY = """
query($project: String!, $cursor: String) {
  issues(
    filter: { project: { name: { eq: $project } } }
    includeArchived: true
    first: 100
    after: $cursor
  ) {
    nodes {
      id identifier title description updatedAt
      state { name type }
      parent { identifier }
      children { nodes { identifier state { name type } } }
      comments(first: 100) {
        nodes {
          body createdAt
          user { email }
          botActor { id }
          isArtificialAgentSessionRoot
        }
        pageInfo { hasNextPage endCursor }
      }
      history(first: 100) {
        nodes {
          createdAt
          fromState { name }
          toState { name }
          descriptionUpdatedBy { id }
        }
        pageInfo { hasNextPage endCursor }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

ISSUE_COMMENTS_QUERY = """
query($id: String!, $cursor: String) {
  issue(id: $id) {
    comments(first: 100, after: $cursor) {
      nodes {
        body createdAt
        user { email }
        botActor { id }
        isArtificialAgentSessionRoot
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

ISSUE_HISTORY_QUERY = """
query($id: String!, $cursor: String) {
  issue(id: $id) {
    history(first: 100, after: $cursor) {
      nodes {
        createdAt
        fromState { name }
        toState { name }
        descriptionUpdatedBy { id }
      }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""

STATES_QUERY = """
query { workflowStates(first: 100) { nodes { id name team { id } } } }
"""

STATE_MUTATION = """
mutation($id: String!, $stateId: String!) {
  issueUpdate(id: $id, input: { stateId: $stateId }) { success }
}
"""


class LinearClient:
    """Thin GraphQL client. `http_post(query, variables) -> response dict` is
    injectable so tests run offline. Swap this class out entirely to point
    the same check/sweep logic at a different tracker."""

    def __init__(self, api_key, http_post=None):
        if not api_key:
            raise ConfigError("LINEAR_API_KEY is empty; mint one and fill "
                              "the .env slot (see .env.example)")
        self.api_key = api_key
        self.http_post = http_post or self._default_post
        self._issue_ids = {}        # identifier -> uuid, filled by fetch
        self._states = None         # name -> id (first team seen wins)

    def _default_post(self, query, variables):
        body = json.dumps({"query": query, "variables": variables}).encode()
        req = urllib.request.Request(
            LINEAR_URL, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": self.api_key})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def fetch_issues(self, project):
        out, cursor = [], None
        while True:
            resp = self.http_post(ISSUES_QUERY,
                                  {"project": project, "cursor": cursor})
            block = resp["data"]["issues"]
            for node in block["nodes"]:
                node["children"] = (node.get("children") or {}).get(
                    "nodes", node.get("children") or [])
                node["comments"] = self._activity_nodes(
                    node["id"], node.get("comments"), "comments",
                    ISSUE_COMMENTS_QUERY)
                node["history"] = self._activity_nodes(
                    node["id"], node.get("history"), "history",
                    ISSUE_HISTORY_QUERY)
                out.append(node)
                self._issue_ids[node["identifier"]] = node["id"]
            page = block["pageInfo"]
            if not page["hasNextPage"]:
                return out
            cursor = page["endCursor"]

    def _activity_nodes(self, issue_id, connection, field, query):
        """Flatten one nested activity connection, following its cursor only
        when an unusually busy ticket exceeds the 100-node inline page."""
        if isinstance(connection, list):
            return connection
        connection = connection or {}
        out = list(connection.get("nodes") or [])
        page = connection.get("pageInfo") or {}
        cursor = page.get("endCursor")
        while page.get("hasNextPage"):
            resp = self.http_post(query, {"id": issue_id, "cursor": cursor})
            connection = resp["data"]["issue"][field]
            out.extend(connection.get("nodes") or [])
            page = connection.get("pageInfo") or {}
            cursor = page.get("endCursor")
        return out

    def set_state(self, issue_identifier, state_name):
        if self._states is None:
            resp = self.http_post(STATES_QUERY, {})
            self._states = {}
            for node in resp["data"]["workflowStates"]["nodes"]:
                self._states.setdefault(node["name"], node["id"])
        state_id = self._states.get(state_name)
        issue_id = self._issue_ids.get(issue_identifier)
        if not state_id or not issue_id:
            return False
        resp = self.http_post(STATE_MUTATION,
                              {"id": issue_id, "stateId": state_id})
        return bool(resp["data"]["issueUpdate"]["success"])


class DryRunClient:
    """--dry-run wrapper: reads pass through to the real client (read-only
    fetch), but set_state is a no-op that records the intended flip and
    returns True so the sweep counts it as a would-fix without mutating the
    tracker. Lets the scheduled `--sweep` command be exercised end-to-end
    with zero side effects."""

    def __init__(self, inner):
        self._inner = inner
        self.would_fix = []

    def fetch_issues(self, project):
        return self._inner.fetch_issues(project)

    def set_state(self, issue_identifier, state_name):
        self.would_fix.append({"issue": issue_identifier, "to": state_name})
        return True


# ---- pure check core --------------------------------------------------------

def _updated_date(node):
    try:
        return date.fromisoformat(node.get("updatedAt", "")[:10])
    except ValueError:
        return None


def _timestamp(value):
    """Parse the tracker's ISO timestamp into an aware datetime, or None."""
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _agent_comment(comment):
    """Whether a comment carries durable agent attribution.

    Native bot/agent metadata wins. Personal-key writes otherwise share the
    owner's account identity, so the tracker-governed session markers are
    required.
    """
    if comment.get("botActor") or comment.get("isArtificialAgentSessionRoot"):
        return True
    return bool(AGENT_COMMENT_RE.search(comment.get("body") or ""))


def _unaddressed_owner_comment(node):
    """Timestamp string when the latest comment is the owner's and no later
    tracked follow-through exists; otherwise None. Always None when
    TICKET_TRACKER_OWNER_EMAIL is unset (the check is dormant until wired).

    A later agent comment necessarily becomes the latest comment. Description
    edits and status changes live in issue history and are checked
    explicitly; unrelated history events do not suppress the alert.
    """
    if not OWNER_EMAIL:
        return None
    if (node.get("state") or {}).get("type") in ("completed", "canceled"):
        return None

    dated = [(at, comment) for comment in node.get("comments") or []
             if (at := _timestamp(comment.get("createdAt"))) is not None]
    if not dated:
        return None
    comment_at, latest = max(dated, key=lambda pair: pair[0])
    email = ((latest.get("user") or {}).get("email") or "").lower()
    if email != OWNER_EMAIL or _agent_comment(latest):
        return None

    for event in node.get("history") or []:
        event_at = _timestamp(event.get("createdAt"))
        if event_at is None or event_at <= comment_at:
            continue
        state_change = event.get("fromState") or event.get("toState")
        description_change = event.get("descriptionUpdatedBy")
        if state_change or description_change:
            return None
    return latest.get("createdAt")


def run_checks(issues, git_window_text, recent_activity_text, decisions_text,
               file_exists, today, plan_docs=None, workstate_docs=None):
    """All checks (a)-(j) over already-fetched issues. Pure: no I/O, no
    network.

    git_window_text: commits since the last sweep (check a evidence).
    recent_activity_text: git log 7d + sessions_index rows 7d (check c).
    plan_docs: [(relpath, {ticket refs}), ...] from the repo's build-doc
      folder; any plan whose ticket is Done is an archive candidate (check i).
      Empty/None -> the check is skipped.
    workstate_docs: [(relpath, {ticket refs}), ...] from plans/workstate/; any
      workstate file whose ticket is Done is past its "deleted at merge"
      lifecycle point (check j). Empty/None -> the check is skipped.
    """
    findings, fixes, signoff = [], [], []
    known = {n["identifier"] for n in issues}
    window_refs = set(SUBJECT_REF_RE.findall(git_window_text or ""))
    recent_refs = set(TICKET_RE.findall(recent_activity_text or ""))
    decision_dates = _decision_dates_by_issue(decisions_text or "")

    def add(sev, msg, path=""):
        findings.append(Finding(sev, "judgment", "ticket_tracker", msg, path))

    for node in issues:
        ident = node["identifier"]
        stype = node["state"]["type"]
        sname = node["state"]["name"]
        desc = node.get("description") or ""

        # (a) commit references a Backlog/Todo ticket -> auto-fix In Progress
        if stype in ("backlog", "unstarted") and ident in window_refs:
            fixes.append({"issue": ident, "to": "In Progress",
                          "reason": "commit references it"})

        # (b) parent In Review with unstarted children -> auto-fix In Progress
        if sname == "In Review" and any(
                c["state"]["type"] in ("backlog", "unstarted")
                for c in node.get("children") or []):
            fixes.append({"issue": ident, "to": "In Progress",
                          "reason": "In Review with unstarted children"})

        # (c) In Progress with no commit or session touch in 7 days -> stale
        if sname == "In Progress" and ident not in recent_refs:
            add("MED", f"{ident} stale: In Progress, no commit or session "
                       f"touch in {STALE_DAYS}d; propose Backlog", ident)

        # (d) all checkboxes checked but ticket unstarted -> flag
        if stype in ("backlog", "unstarted") and CHECKBOX_DONE_RE.search(desc) \
                and not CHECKBOX_OPEN_RE.search(desc):
            add("MED", f"{ident} every checkbox checked but the ticket is "
                       f"{sname}; state drift or scope done", ident)

        # (e) description references files or tickets that no longer exist.
        # Live tickets only (a closed ticket's brief is history, not a
        # contract), and only repo-relative paths: a path whose first
        # segment is not a repo directory is unjudgeable from here.
        if stype not in ("completed", "canceled"):
            for path in sorted(set(FILE_RE.findall(desc))):
                if file_exists(path.split("/")[0]) and not file_exists(path):
                    add("LOW", f"{ident} description references a missing "
                               f"file: {path}", ident)
            for ref in sorted(set(TICKET_RE.findall(desc)) - known - {ident}):
                add("LOW", f"{ident} description references unknown ticket "
                           f"{ref}", ident)

        # (f) decisions.md block naming the ticket newer than its last edit
        upd = _updated_date(node)
        dec = decision_dates.get(ident)
        if upd and dec and dec > upd and stype not in ("completed", "canceled"):
            add("LOW", f"{ident} has a decisions.md block dated {dec} newer "
                       f"than its last edit {upd}; brief may be stale "
                       f"(updatedAt is coarser than description edits)", ident)

        # (g) collect the sign-off queue
        if sname == "In Review":
            signoff.append(ident)

        # (h) a human owner comment with no later agent follow-through. MED
        # is deliberate: the daily ping includes HIGH/MED findings, so an
        # approval cannot silently outlive the run that requested it.
        comment_at = _unaddressed_owner_comment(node)
        if comment_at:
            add("MED", f"{ident} unaddressed comment at {comment_at}: no "
                "later agent comment, description edit, or status change",
                ident)

    # (i) a build-doc naming a Done ticket is an archive candidate. INFO, so
    # it renders in hygiene but never joins the daily ping's need-your-call
    # list.
    done_idents = {n["identifier"] for n in issues
                   if n["state"]["type"] == "completed"}
    for relpath, refs in (plan_docs or []):
        done_refs = sorted(refs & done_idents)
        if done_refs:
            add("INFO", f"{relpath} names Done ticket(s) {', '.join(done_refs)}; "
                "archive candidate (plan shipped, move to archives/)", relpath)

    # (j) a workstate file naming a Done ticket is past its lifecycle point.
    # MED, not INFO: plans/workstate/README.md states workstate "rides the
    # task's feature branch, deleted at merge" -- a Done-ticket file still
    # present is a stronger signal than an un-archived plan (a forgotten
    # cleanup step, not just a deferred one), so it joins the daily ping
    # instead of sitting judgment-only in the weekly view.
    for relpath, refs in (workstate_docs or []):
        done_refs = sorted(refs & done_idents)
        if done_refs:
            add("MED", f"{relpath} names Done ticket(s) {', '.join(done_refs)}; "
                "past its lifecycle point (workstate deletes at merge, delete it)",
                relpath)

    # (g) backpressure: In Review queue + propose-only flags waiting on owner
    waiting = len(signoff) + sum(1 for f in findings if "propose" in f.message)
    if waiting > BACKPRESSURE_CAP:
        findings.insert(0, Finding(
            "HIGH", "judgment", "ticket_tracker",
            f"{waiting} items waiting on the owner (cap {BACKPRESSURE_CAP}): "
            f"backpressure, the queue needs a sign-off pass", ""))

    return CheckResult(findings, fixes, sorted(signoff))


ROLLUP_TITLE_MAX = 40           # truncate titles so rollup lines stay short


def _short_title(node):
    t = (node.get("title") or "").strip()
    if len(t) > ROLLUP_TITLE_MAX:
        t = t[:ROLLUP_TITLE_MAX - 1].rstrip() + "…"
    return t


def _since(node):
    """updatedAt as 'Jul 30' / 'Aug 1' (no %-d; no leading zero), or None."""
    d = _updated_date(node)
    return d.strftime("%b ") + str(d.day) if d else None


def build_rollup(issues, recent_refs, seen_idents, today):
    """Weekly open-tickets backstop. Pure, offline.

    The complete open-actionable set, split by novelty: net-new items (not
    pinged this week) get detailed lines with a why-clause; items already
    seen this week collapse to one terse tail. Three buckets:
      - In Review: all open (owner's sign-off, no threshold).
      - Stale In Progress: In Progress with no recent commit/session touch
        (same predicate as check (c): ident not in recent_refs).
      - Aging Todo: unstarted with updatedAt older than STALE_DAYS.
    Backlog/Done/Canceled never appear. Empty board returns the all-clear
    line.
    """
    recent_refs = recent_refs or set()
    seen_idents = seen_idents or set()
    review, stale_ip, aging_todo, seen = [], [], [], []
    total = 0

    for node in issues:
        ident = node["identifier"]
        sname = node["state"]["name"]
        stype = node["state"]["type"]

        if sname == "In Review":
            bucket = "review"
        elif sname == "In Progress" and ident not in recent_refs:
            bucket = "stale"
        elif stype == "unstarted":
            d = _updated_date(node)
            bucket = "todo" if d and (today - d).days > STALE_DAYS else None
        else:
            bucket = None
        if bucket is None:
            continue

        total += 1
        if ident in seen_idents:
            seen.append(ident)
            continue

        title = _short_title(node)
        if bucket == "review":
            review.append(f"{ident} ({title})")
        elif bucket == "stale":
            since = _since(node)
            stale_ip.append(f"{ident} ({title}, quiet since {since})" if since
                            else f"{ident} ({title})")
        else:
            since = _since(node)
            aging_todo.append(f"{ident} ({title}, idle since {since})" if since
                              else f"{ident} ({title})")

    if total == 0:
        return "Weekly backstop: 0 open, all clear"

    lines = [f"Weekly open-tickets backstop ({total} need action):"]
    if review:
        lines.append("In Review (your call): " + ", ".join(review))
    if stale_ip:
        lines.append("Stale In Progress (7d+): " + ", ".join(stale_ip))
    if aging_todo:
        lines.append("Aging Todo (7d+): " + ", ".join(aging_todo))
    if seen:
        lines.append(f"Plus {len(seen)} still open, seen this week: "
                     + ", ".join(seen))
    return "\n".join(lines)


def _daily_pinged_idents(fixed, result):
    """The ticket IDs a daily ping references: auto-fixed flips, per-finding
    paths (check (c) etc.; the empty-path backpressure line is skipped), and
    the In Review sign-off queue."""
    idents = {f["issue"] for f in fixed}
    idents |= {f.path for f in result.findings if f.path}
    idents |= set(result.signoff_queue)
    return idents


def _decision_dates_by_issue(text):
    """identifier -> newest decisions.md block date that names it."""
    out = {}
    current = None
    for line in text.splitlines():
        m = DECISION_HEADER_RE.match(line)
        if m:
            try:
                current = date.fromisoformat(m.group(1))
            except ValueError:
                current = None
            continue
        if current is None:
            continue
        for ref in TICKET_RE.findall(line):
            if ref not in out or current > out[ref]:
                out[ref] = current
    return out


# ---- repo evidence gathering (I/O) -----------------------------------------

def _git_log(root, since):
    try:
        proc = subprocess.run(
            ["git", "log", f"--since={since}", "--pretty=%s%n%b"],
            cwd=root, capture_output=True, text=True, timeout=30)
        return proc.stdout if proc.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _sessions_recent(root, today, days):
    """sessions_index rows whose date cell is within `days`."""
    path = os.path.join(root, "records", "sessions_index.md")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    keep = []
    floor = today - timedelta(days=days)
    for line in text.splitlines():
        m = re.match(r"\|\s*(\d{4}-\d{2}-\d{2})", line)
        if not m:
            continue
        try:
            if date.fromisoformat(m.group(1)) >= floor:
                keep.append(line)
        except ValueError:
            continue
    return "\n".join(keep)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


PLAN_DOC_DIRS = ("plans", "docs")


def _plan_docs(root):
    """(relpath, {ticket refs}) per build doc in the repo's plans/ dir (or
    docs/, if that's your convention). Refs are drawn from the filename and
    the first markdown heading. Feeds check (i): a plan whose ticket is Done
    is an archive candidate."""
    for sub in PLAN_DOC_DIRS:
        d = os.path.join(root, sub)
        if os.path.isdir(d):
            break
    else:
        return []
    out = []
    for name in sorted(os.listdir(d)):
        path = os.path.join(d, name)
        if not name.endswith(".md") or name == "README.md" or not os.path.isfile(path):
            continue
        head = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("#"):
                        head = line
                        break
        except OSError:
            pass
        refs = set(TICKET_RE.findall(name)) | set(TICKET_RE.findall(head))
        if refs:
            out.append((f"{sub}/{name}", refs))
    return out


def _workstate_docs(root):
    """(relpath, {ticket refs}) per file directly under plans/workstate/.
    Same filename+heading ref extraction as _plan_docs. Skips README.md and
    subdirectories (a multi-artifact run's own folder, out of scope for this
    mechanical check). Feeds check (j): a Done-ticket workstate file is past
    its 'deleted at merge' lifecycle point (plans/workstate/README.md)."""
    d = os.path.join(root, "plans", "workstate")
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        path = os.path.join(d, name)
        if not name.endswith(".md") or name == "README.md" or not os.path.isfile(path):
            continue
        head = ""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("#"):
                        head = line
                        break
        except OSError:
            pass
        refs = set(TICKET_RE.findall(name)) | set(TICKET_RE.findall(head))
        if refs:
            out.append((f"plans/workstate/{name}", refs))
    return out


def gather_evidence(root, today, since):
    return {
        "git_window_text": _git_log(root, since),
        "recent_activity_text": (_git_log(root, f"{STALE_DAYS} days ago") + "\n"
                                 + _sessions_recent(root, today, STALE_DAYS)),
        "decisions_text": _read(os.path.join(root, "records", "decisions.md")),
        "file_exists": lambda p: os.path.exists(os.path.join(root, p)),
        "plan_docs": _plan_docs(root),
        "workstate_docs": _workstate_docs(root),
    }


# ---- check mode (read-only, imported by hygiene_check) ----------------------

def check(root=None, client=None, today=None):
    """Read-only findings for the hygiene checker's group-7 hook. Raises
    ConfigError when the board or the key is not configured; network errors
    bubble to the caller (hygiene degrades to a note)."""
    root = root or os.getcwd()
    today = today or date.today()
    if not PROJECTS and client is None:
        raise ConfigError("TICKET_TRACKER_PROJECTS is empty; set it in .env "
                          "to the board/project name(s) you want tracked "
                          "(see operations.md Connectors)")
    client = client or LinearClient(_load_key(root))
    issues = []
    for project in PROJECTS:
        issues.extend(client.fetch_issues(project))
    ev = gather_evidence(root, today, f"{STALE_DAYS} days ago")
    return run_checks(issues, today=today, **ev)


def _load_key(root):
    """LINEAR_API_KEY: env, then ~/.secrets/shared.env, then repo .env
    (governance/secrets.md)."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key
    for path in (os.path.expanduser("~/.secrets/shared.env"),
                 os.path.join(root, ".env")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("LINEAR_API_KEY="):
                        val = line.split("=", 1)[1].strip().strip("\"'")
                        if val:
                            return val
        except OSError:
            continue
    return ""


# ---- sweep mode -------------------------------------------------------------

def sweep(client, projects, state_path, git_window_text, recent_activity_text,
          decisions_text, file_exists, today, plan_docs=None,
          workstate_docs=None):
    """Apply auto-fixes, persist the cursor, and return {"fixed", "ping",
    "findings"}. `ping` is None when the board is clean (silent day)."""
    issues = []
    for project in projects:
        issues.extend(client.fetch_issues(project))
    result = run_checks(issues, git_window_text, recent_activity_text,
                        decisions_text, file_exists, today, plan_docs,
                        workstate_docs)

    fixed = []
    for fix in result.fixes:
        if client.set_state(fix["issue"], fix["to"]):
            fixed.append(fix)

    ping = _ping_text(fixed, result) if (
        fixed or result.findings or result.signoff_queue) else None

    # Per-ISO-week pinged-ID set: resets Monday, accumulates through Sunday,
    # so on Sunday it holds exactly what was pinged this week.
    state = _read_state(state_path)
    week = _iso_week(today)
    pinged = set(state.get("pinged", [])) if state.get("week") == week else set()
    pinged |= _daily_pinged_idents(fixed, result)

    if today.weekday() == 6:        # Sunday: weekly open-tickets backstop
        recent_refs = set(TICKET_RE.findall(recent_activity_text or ""))
        rollup = build_rollup(issues, recent_refs, pinged, today)
        ping = (ping + "\n\n" + rollup) if ping else rollup

    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"last_run": today.isoformat(), "week": week,
                   "pinged": sorted(pinged)}, f)

    return {"fixed": len(fixed), "ping": ping, "findings": result.findings}


def _ping_text(fixed, result):
    need_call = [f for f in result.findings if f.severity in ("HIGH", "MED")]
    header = (f"Tracker drift: auto-fixed {len(fixed)}, "
              f"need your call on {len(need_call) + len(result.signoff_queue)}.")
    lines = [header]
    for fix in fixed:
        lines.append(f"- fixed: {fix['issue']} -> {fix['to']} ({fix['reason']})")
    for f in need_call:
        lines.append(f"- {f.message}")
    if result.signoff_queue:
        lines.append("- Done sign-off queue: " + ", ".join(result.signoff_queue)
                     + " (mark it Done in your tracker once you agree)")
    return "\n".join(lines)


def _read_state(state_path):
    """The persisted sweep state ({last_run, week, pinged}), or {} when
    absent or unreadable. Missing keys default clean at each call site
    (back-compat)."""
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _iso_week(today):
    iso = today.isocalendar()       # (ISO year, ISO week, ISO weekday)
    return f"{iso[0]}-W{iso[1]:02d}"


def _last_run(state_path, today):
    return (_read_state(state_path).get("last_run")
            or (today - timedelta(days=STALE_DAYS)).isoformat())


def _send_ping(root, text):
    """Route the ping through the egress gate's `tracker-ping` verb (the
    example classification ships it posture 'auto' with a placeholder echo
    exec; swap the exec for your own notification command). Falls back to
    the ping file alone when the gate isn't wired or the send fails."""
    shim = os.path.join(root, "scripts", "egress_gate", "egress.py")
    try:
        proc = subprocess.run(
            [sys.executable, shim, "tracker-ping", "--text", text],
            capture_output=True, text=True, timeout=60)
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--sweep", action="store_true")
    ap.add_argument("--root", default=os.getcwd())
    ap.add_argument("--no-ping", action="store_true",
                    help="sweep without sending (supervised first runs)")
    ap.add_argument("--dry-run", action="store_true",
                    help="sweep with no side effects: no tracker mutation, "
                         "no ping send, real cursor untouched (proof / preview)")
    args = ap.parse_args(argv)
    root, today = args.root, date.today()

    if not PROJECTS:
        print("ticket_tracker: TICKET_TRACKER_PROJECTS is not set; nothing "
              "to track. Set it in .env to your board/project name(s) "
              "(operations.md Connectors).", file=sys.stderr)
        return 2

    if args.check:
        result = check(root=root, today=today)
        for f in result.findings:
            print(f"[{f.severity}][{f.tag}] {f.message}")
        print(f"# {len(result.fixes)} auto-fixable, "
              f"{len(result.signoff_queue)} awaiting sign-off")
        return 0

    client = LinearClient(_load_key(root))
    # --dry-run: block tracker mutations and route state to a throwaway
    # cursor so the real weekly cursor never advances from a proof run.
    if args.dry_run:
        client = DryRunClient(client)
        state_rel = STATE_PATH.replace("state.json", "state.dryrun.json")
        ping_rel = PING_PATH.replace("ping.md", "ping.dryrun.md")
    else:
        state_rel, ping_rel = STATE_PATH, PING_PATH
    state_path = os.path.join(root, state_rel)
    ev = gather_evidence(root, today, _last_run(state_path, today))
    result = sweep(client, PROJECTS, state_path, today=today, **ev)
    if result["ping"]:
        ping_path = os.path.join(root, ping_rel)
        os.makedirs(os.path.dirname(ping_path), exist_ok=True)
        with open(ping_path, "w", encoding="utf-8") as f:
            f.write(result["ping"] + "\n")
        # dry-run never sends; otherwise --no-ping suppresses the send.
        sent = False if (args.dry_run or args.no_ping) else _send_ping(
            root, result["ping"])
        out = {"fixed": result["fixed"], "ping_sent": sent, "ping_file": ping_rel}
        if args.dry_run:
            out.update(dry_run=True, would_fix=client.would_fix)
        print(json.dumps(out))
    else:
        out = {"fixed": 0, "ping_sent": False, "clean": True}
        if args.dry_run:
            out["dry_run"] = True
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
