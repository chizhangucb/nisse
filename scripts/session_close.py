#!/usr/bin/env python3
"""Session-close sweeper.

Spawned detached by the SessionStart hook. Sweeps the hub ledger for
`(pending)` rows whose session is done (a SessionEnd done-marker exists, or the
row's last-activity timestamp is older than STALE_HOURS), skips the session
that just started, and for each done session:

- distills each due session's transcript deterministically (user + assistant
  text only, tool noise dropped, char-capped), then batches up to BATCH_SIZE
  sessions per one-shot headless `claude -p` call (env-guarded so its own
  transcript never hits the ledger), no tools, returning JSON:
  {"sessions": [{"id": "<short>", "focus": "<=15 words", "decisions": [...]}]}
  One-shot on a mid-tier model, never an agentic session: the agentic shape
  costs orders of magnitude more for a 15-word focus line.
- writes the focus into the ledger row (mechanics here, judgment in the model)
- if the session has no block of its own in records/decisions.jsonl, appends
  any decided blocks there via aios_ledger.append_decision (validated, one
  row per decision block, idempotent per session+stream)

Precision over recall on decisions: the prompt only stages a decision on an
explicit, clear yes from the owner; uncertain means stage nothing. A wrongly
missed decision is recoverable; a false block in the source of truth is not.

Standing policy: focus lines are always auto-written; decisions are auto-written
only on a clear explicit-yes signal, and only for a cold session with no block
of its own, always with the one-line notice next SessionStart so the owner can
veto. A warm session that logged its own block is trusted and never re-touched.

State lives in <hub>/.claude/state/session-close/ (gitignored):
done/<sid> markers, staging/<sid>.md drafts, lock, last-run.json (feeds the
one-line "auto-logged N decisions" notice the next SessionStart surfaces).
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys
import time

import aios_ledger  # append-only JSONL ledger store (sessions.jsonl + decisions.jsonl)

STALE_HOURS = 24
LOCK_MAX_AGE_MIN = 30
FOCUS_WORD_CAP = 15
MODEL = "sonnet"              # mid-tier is plenty for a 15-word summary
CLAUDE_TIMEOUT_S = 300
DIGEST_CHAR_CAP = 60000       # ~15K tokens of distilled conversation
DIGEST_HEAD_CHARS = 20000     # over cap: keep the head, elide the middle,
DIGEST_TAIL_CHARS = 40000     # tail-biased (approvals cluster late)
SUBSESSION_CWD = "/tmp/aios-session-close"

# One model call summarizes up to this many done sessions at once instead of
# one call per session; a batch of 1 degrades gracefully.
BATCH_SIZE = 6

PROMPT_BATCH_TEMPLATE = """You are the AIOS session-close summarizer. Below are {n} distilled agent session transcripts, each the owner's messages and the assistant's replies, tool activity stripped, possibly elided in the middle. Each is marked "--- SESSION <id> (stream: <repo>) ---".

Return ONLY a JSON object, no prose, no code fences, with exactly one entry per session below, using its exact id:
{{"sessions": [{{"id": "<session id>", "focus": "<=15 word summary of what the session worked on", "decisions": []}}, ...]}}

Focus: concrete and specific, <=15 words.

Decisions: precision first, default to an empty list per session. Include an entry ONLY if BOTH hold:
1. The transcript shows the owner explicitly saying yes to a named choice (a clear approval, not silence, not an implied preference).
2. It meets the logging bar: changes future behavior (policy, structure, schema, rule), commits something hard to undo, or settles a question a future session would re-litigate. Never task completions, never one-off choices.
If uncertain about either, leave it out.

One session = one block of decisions. Group ALL of a session's decisions into a SINGLE entry: one title that captures the session's theme, then one bullet per decision. Do not emit a separate entry per decision.
Entry shape: {{"title": "short title covering the session", "stream": "<stream>", "bullets": ["- **First decision.** Short why. → pointer", "- **Second decision.** Short why. → pointer"]}}
So a session's "decisions" holds at most one entry. Every bullet starts with "- **". Aim ~30 words per bullet. For a session marked "stream: hub", pick the stream the work belongs to (default "hub"); for any other marked stream, use that stream as given.

Transcripts:
{sessions_block}"""

SESSION_BLOCK_TEMPLATE = """
--- SESSION {id} (stream: {stream}) ---
{digest}
--- END SESSION {id} ---
"""


# ---------------------------------------------------------------------------
# Paths and state
# ---------------------------------------------------------------------------

def state_dir(hub):
    return os.path.join(hub, ".claude", "state", "session-close")


def find_hub():
    env = os.environ.get("AIOS_HUB")
    candidates = []
    if env:
        candidates.append(os.path.expanduser(env))
    candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for c in candidates:
        # The hub marker is now records/sessions.jsonl; accept the legacy
        # sessions_index.md too so hub-detection works through the bake.
        if os.path.exists(os.path.join(c, "records", "sessions.jsonl")) \
                or os.path.exists(os.path.join(c, "records", "sessions_index.md")):
            return c
    return None


# ---------------------------------------------------------------------------
# Lock: one sweeper at a time across however many SessionStarts fired
# ---------------------------------------------------------------------------

def acquire_lock(hub):
    lock = os.path.join(state_dir(hub), "lock")
    os.makedirs(state_dir(hub), exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        try:
            age_min = (time.time() - os.path.getmtime(lock)) / 60
        except OSError:
            return False
        if age_min <= LOCK_MAX_AGE_MIN:
            return False
        # Stale lock from a dead sweeper: take it over.
        try:
            os.remove(lock)
        except OSError:
            pass
        return acquire_lock(hub)


def release_lock(hub):
    try:
        os.remove(os.path.join(state_dir(hub), "lock"))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Ledger reads (records/sessions.jsonl via aios_ledger, the single write path)
# ---------------------------------------------------------------------------

def pending_rows(hub):
    """[(stamp, sid, repo)] for every (pending) session. Reads sessions.jsonl
    via aios_ledger.pending_sessions (was a markdown-table scan)."""
    return aios_ledger.pending_sessions(hub)


def is_done(hub, short, stamp, now=None):
    """Done = graceful-exit marker exists, or last activity is stale."""
    done_dir = os.path.join(state_dir(hub), "done")
    if glob.glob(os.path.join(done_dir, short + "*")):
        return True
    try:
        last = datetime.datetime.strptime(stamp, "%Y-%m-%d %H%M")
    except ValueError:
        return False
    now = now or datetime.datetime.now()
    return (now - last) > datetime.timedelta(hours=STALE_HOURS)


def projects_dir_for(hub):
    """The ~/.claude/projects folder holding this hub's transcripts."""
    munged = os.path.abspath(hub).replace("/", "-").replace(".", "-")
    return os.path.expanduser(os.path.join("~", ".claude", "projects", munged))


# Stub transcripts stay tiny (a few metadata lines); anything bigger is not
# worth parsing and is never a stub we want to delete.
STUB_MAX_BYTES = 8192


def is_stub_transcript(path):
    """True if the transcript holds zero real turns: only metadata lines, no
    user or assistant message."""
    try:
        if os.path.getsize(path) > STUB_MAX_BYTES:
            return False
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if json.loads(line).get("type") in ("user", "assistant"):
                    return False
    except (OSError, ValueError):
        return False
    return True


def reap_stub_transcripts(hub, current, now=None):
    """Delete zero-turn stub transcripts from the hub's projects folder.

    The harness mints a session id and drops a 2-line metadata file for tabs
    that open and close without a real turn; they clutter the folder and read
    as mystery sessions. Delete a stub only when its session has provably
    ended (a done-marker exists) or its mtime is older than STALE_HOURS, and
    never the just-started session's. Returns the count deleted."""
    now = now or datetime.datetime.now()
    cur_short = (current or "")[:8]
    done_dir = os.path.join(state_dir(hub), "done")
    reaped = 0
    for path in glob.glob(os.path.join(projects_dir_for(hub), "*.jsonl")):
        sid = os.path.basename(path)[:-len(".jsonl")]
        if cur_short and sid.startswith(cur_short):
            continue
        if not is_stub_transcript(path):
            continue
        ended = bool(glob.glob(os.path.join(done_dir, sid[:8] + "*")))
        if not ended:
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue
            if (now - mtime) <= datetime.timedelta(hours=STALE_HOURS):
                continue
        try:
            os.remove(path)
            reaped += 1
        except OSError:
            pass
    return reaped


def find_transcript(short):
    """Newest transcript whose filename starts with the short session id."""
    hits = glob.glob(os.path.expanduser(
        os.path.join("~", ".claude", "projects", "*", short + "*.jsonl")))
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


_SYS_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>",
                              re.DOTALL)


def distill_transcript(path):
    """Deterministic digest: user + assistant text only, tool noise dropped.

    Tool results are ~90% of transcript bytes; this pre-filter makes a one-shot
    no-tools call sufficient. Returns None if unreadable, "" if no
    conversational content (stub), else "Owner:"/"Assistant:"-labeled turns,
    char-capped with a tail-biased head+tail split (approvals cluster late).
    """
    try:
        f = open(path)
    except OSError:
        return None
    turns = []
    with f:
        for ln in f:
            try:
                obj = json.loads(ln)
            except ValueError:
                continue
            kind = obj.get("type")
            if kind not in ("user", "assistant") or obj.get("isMeta"):
                continue
            content = (obj.get("message") or {}).get("content")
            texts = []
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                texts.extend(c.get("text") or "" for c in content
                             if isinstance(c, dict) and c.get("type") == "text")
            text = _SYS_REMINDER_RE.sub("", "\n".join(texts)).strip()
            if not text:
                continue
            turns.append(("Owner: " if kind == "user" else "Assistant: ") + text)
    digest = "\n\n".join(turns)
    if len(digest) > DIGEST_CHAR_CAP:
        digest = (digest[:DIGEST_HEAD_CHARS]
                  + "\n\n[... middle of session elided ...]\n\n"
                  + digest[-DIGEST_TAIL_CHARS:])
    return digest


def write_focus(hub, sid, focus):
    """Fill this session's (pending) row, found by id, under the sessions lock
    (aios_ledger.set_focus over sessions.jsonl). Only touches a still-pending
    row, so it is idempotent and safe against a live Stop hook."""
    return aios_ledger.set_focus(hub, sid, focus)


# ---------------------------------------------------------------------------
# Summarizer call (injectable for tests)
# ---------------------------------------------------------------------------

def default_runner(prompt, hub):
    """One headless claude call; returns the result text or None on failure.

    Runs from a throwaway cwd (not the hub) so the sub-session's own transcript
    lands in its own ~/.claude/projects/ folder instead of polluting the hub's.
    One-shot: the digest is inline in the prompt and --tools "" disables all
    tools, so the call cannot go agentic. This is what keeps the sweeper cheap;
    never widen it back to an agentic call without a cost line in a reviewed
    plan.
    """
    cmd = ["claude", "-p", prompt, "--model", MODEL,
           "--output-format", "json", "--tools", ""]
    env = dict(os.environ, AIOS_CLOSE_SUBSESSION="1")
    subsession_cwd = SUBSESSION_CWD
    os.makedirs(subsession_cwd, exist_ok=True)
    try:
        proc = subprocess.run(cmd, cwd=subsession_cwd, capture_output=True,
                              text=True, env=env, timeout=CLAUDE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout).get("result")
    except ValueError:
        return None


def build_batch_prompt(items):
    """items: [(short, stream, digest)]. One prompt carrying every session in
    this batch, each in its own labeled block."""
    blocks = [SESSION_BLOCK_TEMPLATE.format(id=short, stream=stream,
                                            digest=digest)
             for short, stream, digest in items]
    return PROMPT_BATCH_TEMPLATE.format(n=len(items),
                                        sessions_block="".join(blocks))


def parse_batch_result(text):
    """The model's batched JSON: {"sessions": [{"id", "focus", "decisions"}]}.

    Returns {id: {"focus": ..., "decisions": [...]}} for every well-formed
    entry, tolerating stray prose/fences and dropping malformed entries
    individually rather than failing the whole batch.
    """
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    sessions = obj.get("sessions")
    if not isinstance(sessions, list):
        return None
    out = {}
    for s in sessions:
        if not isinstance(s, dict):
            continue
        sid = (s.get("id") or "").strip()
        focus = (s.get("focus") or "").strip()
        if not sid or not focus:
            continue
        out[sid] = s
    return out


# ---------------------------------------------------------------------------
# Decisions: warm check, block formatting, mechanical appender
# ---------------------------------------------------------------------------

def has_own_block(hub, sid):
    """True when decisions.jsonl already carries a block for this session (warm).
    aios_ledger.session_has_decision_block, prefix-tolerant."""
    return aios_ledger.session_has_decision_block(hub, sid)


def merge_decisions(decisions):
    """Collapse a session's staged decisions into one block per stream.

    The rule is one session = one block, keyed by session ID, scoped by stream
    (decisions.md header). A session that settled several things is ONE block
    with several bullets, not several one-bullet blocks. Group by stream in
    first-seen order; the first entry's title heads its stream's block; bullets
    concatenate. Safeguard so a model that still emits separate entries per
    decision collapses to the right shape."""
    groups, order = {}, []
    for d in decisions:
        stream = (d.get("stream") or "").strip()
        if stream not in groups:
            groups[stream] = {"title": (d.get("title") or "").strip(),
                              "stream": stream, "bullets": []}
            order.append(stream)
        if not groups[stream]["title"]:
            groups[stream]["title"] = (d.get("title") or "").strip()
        groups[stream]["bullets"].extend(d.get("bullets") or [])
    return [groups[s] for s in order]


def build_decision_row(date, short, decision):
    """One staged decision as a validated decisions.jsonl ROW (was format_block's
    markdown string), or None if invalid. The body is the verbatim bullet lines;
    aios_ledger.validate_decision enforces the header shape, the bullet/note body
    shape, and the em-dash ban."""
    title = (decision.get("title") or "").strip().rstrip(".")
    stream = (decision.get("stream") or "").strip()
    bullets = [b.strip() for b in decision.get("bullets") or [] if b.strip()]
    if not title or not stream or not bullets:
        return None
    if not all(b.startswith("- **") for b in bullets):
        return None
    body = "\n".join(bullets)
    if aios_ledger.validate_decision(date=date, title=title, session=short,
                                     stream=stream, body=body) is not None:
        return None
    return {"date": date, "title": title, "session": short,
            "stream": stream, "body": body}


def append_rows(hub, rows):
    """Append validated decision rows to decisions.jsonl (was the markdown
    append_blocks). Idempotent per (session, stream) at the append layer;
    returns the count actually written."""
    n = 0
    for row in rows:
        ok, _reason = aios_ledger.append_decision(
            hub, date=row["date"], title=row["title"], session=row["session"],
            stream=row["stream"], body=row["body"])
        if ok:
            n += 1
    return n


# ---------------------------------------------------------------------------
# Genesis: create rows for sessions the Stop hook never landed
# ---------------------------------------------------------------------------

def _parse_satellites(text):
    """Rows (dicts keyed by header) of the first table under `## Satellites`.
    Mirrors .claude/hooks/session-ledger.py so both read the registry the same
    way."""
    m = re.search(r"(?m)^## Satellites[^\n]*\n", text)
    if not m:
        return []
    rest = text[m.end():]
    nxt = re.search(r"(?m)^#{1,6} ", rest)
    body = rest[:nxt.start()] if nxt else rest
    header, rows = None, []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(set(c) <= set("-: ") for c in cells):
            continue  # separator row
        if header is None:
            header = cells
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _collapse_worktree(p):
    """Collapse a git-worktree path under <repo>/.claude/worktrees/<name> down
    to its parent repo root; a worktree session belongs to the parent's label."""
    return re.sub(r"/\.claude/worktrees/[^/]+(?:/.*)?$", "", p) if p else p


def _munge_path(path):
    """A cwd's ~/.claude/projects folder name, the way the harness encodes it.
    Collapse a worktree path to its parent first, so a worktree and its parent
    repo map to the same folder."""
    abs_path = _collapse_worktree(os.path.abspath(os.path.expanduser(path)))
    return abs_path.replace("/", "-").replace(".", "-")


def _genesis_folders(hub):
    """[(projects_folder, label)] to scan: the hub plus each registered
    satellite, label being `hub` or the satellite's name from operations.md."""
    folders = [(projects_dir_for(hub), "hub")]
    try:
        with open(os.path.join(hub, "operations.md")) as f:
            text = f.read()
    except OSError:
        text = ""
    base = os.path.expanduser(os.path.join("~", ".claude", "projects"))
    for row in _parse_satellites(text):
        raw = (row.get("Repo path", "") or "").strip().strip("`")
        name = (row.get("Satellite", "") or "").strip()
        if raw and name:
            folders.append((os.path.join(base, _munge_path(raw)), name))
    return folders


def _insert_pending_row(hub, stamp, sid, label):
    """Insert a (pending) row for the session id if still absent, under the
    sessions lock (aios_ledger.insert_pending_if_absent over sessions.jsonl).
    The under-lock re-check makes a concurrent late Stop hook unable to
    duplicate the row."""
    return aios_ledger.insert_pending_if_absent(hub, session=sid, stamp=stamp,
                                                repo=label)


def genesis_create_rows(hub, current, now=None, dry_run=False):
    """Create a (pending) row for every row-less, non-stub, done session in the
    hub + satellite projects folders.

    The backstop for sessions whose Stop hook never landed a row (SDK/queue
    turns that fire Stop rarely, or writes dropped by a race). The sweep fills
    each new row's focus in the same pass. Recall-first, the inverse of the
    decisions stance: a spurious row is cheap and retirable, an invisible
    session is the failure. Returns the count created."""
    now = now or datetime.datetime.now()
    cur_short = (current or "")[:8]
    existing = aios_ledger.session_ids(hub)
    done_dir = os.path.join(state_dir(hub), "done")
    created = 0
    for folder, label in _genesis_folders(hub):
        for path in glob.glob(os.path.join(folder, "*.jsonl")):
            sid = os.path.basename(path)[:-len(".jsonl")]
            if cur_short and (sid.startswith(cur_short)
                              or cur_short.startswith(sid)):
                continue
            if sid in existing or is_stub_transcript(path):
                continue
            try:
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue
            ended = bool(glob.glob(os.path.join(done_dir, sid + "*")))
            if not ended and (now - mtime) <= datetime.timedelta(hours=STALE_HOURS):
                continue  # still live: leave it for a later sweep
            stamp = mtime.strftime("%Y-%m-%d %H%M")
            if dry_run or _insert_pending_row(hub, stamp, sid, label):
                created += 1
                existing.add(sid)
    return created


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def clear_marker(hub, short):
    for p in glob.glob(os.path.join(state_dir(hub), "done", short + "*")):
        try:
            os.remove(p)
        except OSError:
            pass


def reap_orphan_markers(hub, pending_shorts, current):
    """Delete done-markers with no matching pending ledger row.

    A marker is dropped for every session at SessionEnd, but the sweep only
    clears markers whose session still has a (pending) row; the rest would sit
    forever. Reap any such orphan; never touch the just-started session's."""
    cur_short = (current or "")[:8]
    reaped = 0
    for p in glob.glob(os.path.join(state_dir(hub), "done", "*")):
        marker = os.path.basename(p)
        if cur_short and (marker.startswith(cur_short) or cur_short.startswith(marker)):
            continue
        if any(marker.startswith(s) or s.startswith(marker) for s in pending_shorts):
            continue
        try:
            os.remove(p)
            reaped += 1
        except OSError:
            pass
    return reaped


def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _apply_result(hub, stamp, short, result, logged):
    """Apply one session's parsed result: write its focus, append its decisions
    if cold, clear its marker. Returns True if the focus was written (i.e. this
    session's row still had a matching pending cell)."""
    filled = write_focus(hub, short, result["focus"].strip())
    if not has_own_block(hub, short):
        date = stamp.split()[0]
        rows, titles = [], []
        for d in merge_decisions(result.get("decisions") or []):
            row = build_decision_row(date, short, d)
            if row:
                rows.append(row)
                titles.append(d.get("title", "").strip())
        if append_rows(hub, rows):
            logged.append({"session": short, "titles": titles})
    clear_marker(hub, short)
    return filled


def sweep(hub, current, runner=default_runner, now=None, dry_run=False):
    """One full pass. Returns a summary dict (also written to last-run.json).

    Sessions due for a focus fill are collected first, then swept through the
    model BATCH_SIZE at a time. dry_run short-circuits every mutation but
    still returns an accurate plan of what it WOULD do.
    """
    created = genesis_create_rows(hub, current, now=now, dry_run=dry_run)
    cur_short = (current or "")[:8]
    logged = []
    filled = 0
    pending = pending_rows(hub)
    pending_ids = [sid for _, sid, _ in pending]

    due = []  # [(stamp, sid, repo, digest)]
    for stamp, short, repo in pending:
        if cur_short and (short.startswith(cur_short) or cur_short.startswith(short)):
            continue
        if not is_done(hub, short, stamp, now=now):
            continue
        transcript = find_transcript(short)
        digest = distill_transcript(transcript) if transcript else None
        if not digest:
            # Missing, unreadable, or no conversational content: nothing to
            # summarize. Retire the eternal (pending) row (write_focus only
            # fills still-pending rows, so this is safe and idempotent) and
            # drop the marker so we stop retrying.
            if not dry_run:
                write_focus(hub, short, "(no captured turns)")
                clear_marker(hub, short)
            continue
        due.append((stamp, short, repo, digest))

    if dry_run:
        filled = len(due)
    else:
        for batch in _chunk(due, BATCH_SIZE):
            items = [(short, repo, digest) for _, short, repo, digest in batch]
            prompt = build_batch_prompt(items)
            results = parse_batch_result(runner(prompt, hub))
            if results is None:
                continue  # whole batch failed to parse: keep markers, retry later
            for stamp, short, _repo, _digest in batch:
                result = results.get(short)
                if result is None:
                    continue  # missing from the response: retry later
                if _apply_result(hub, stamp, short, result, logged):
                    filled += 1

    stubs = 0 if dry_run else reap_stub_transcripts(hub, current, now=now)
    reaped = 0 if dry_run else reap_orphan_markers(hub, pending_ids, current)
    own = 0 if dry_run else reap_own_transcripts()
    summary = {"created": created, "filled": filled, "logged": logged,
               "noted": not logged, "reaped": reaped, "stubs": stubs,
               "own": own}
    if not dry_run:
        _write_last_run(hub, summary)
    return summary


def reap_own_transcripts():
    """Delete the sweeper's own sub-session transcripts.

    Every default_runner call leaves a transcript under ~/.claude/projects/
    for SUBSESSION_CWD; they carry no state (outputs land in the ledger and
    decisions.md) and only accumulate. The lock guarantees no other sweeper
    is mid-run. realpath because /tmp is /private/tmp on macOS."""
    folder = os.path.realpath(SUBSESSION_CWD).replace(os.sep, "-")
    d = os.path.expanduser(os.path.join("~", ".claude", "projects", folder))
    n = 0
    for p in glob.glob(os.path.join(d, "*.jsonl")):
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
    return n


def _write_last_run(hub, summary):
    os.makedirs(state_dir(hub), exist_ok=True)
    with open(os.path.join(state_dir(hub), "last-run.json"), "w") as f:
        json.dump(summary, f, indent=2)


LEDGER_REF = "refs/ledger/checkpoints"
# Snapshot the new jsonl truth plus the legacy markdown while it still exists
# through the bake (the present-filter below drops any that are absent).
LEDGER_PATHS = ["records/sessions.jsonl", "records/decisions.jsonl",
                "records/sessions_index.md", "records/decisions.md"]


def _checkpoint_ledger(hub, dry_run=False):
    """Snapshot the two record streams onto a dedicated ref, off `main`.

    Durability without polluting `main`'s linear history. The periodic sweep is
    the checkpoint home: it closes the uncommitted-window hole where a stale git
    blob replay could clobber a long-uncommitted ledger. We snapshot the two
    files to `refs/ledger/checkpoints` using a throwaway index, so `main`/HEAD
    and its index are never touched and `git log` stays clean. Recover a
    clobbered file with `git cat-file blob refs/ledger/checkpoints:<path>`;
    browse history with `git log refs/ledger/checkpoints`. Idempotent: a no-op
    when the snapshot matches the last checkpoint. Best-effort: swallows every
    git error, since a sandboxed spawn may not be able to write and the next
    sweep gets it. Never pushes (the egress gate owns push)."""
    if dry_run:
        return
    tmp_index = os.path.join(hub, ".git", "ledger-checkpoint.index")
    env = dict(os.environ, GIT_INDEX_FILE=tmp_index)

    def git(*args, use_index=False):
        return subprocess.run(["git"] + list(args), cwd=hub,
                              capture_output=True, text=True,
                              env=env if use_index else None)
    try:
        if git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return  # not a git work tree
        present = [p for p in LEDGER_PATHS
                   if os.path.exists(os.path.join(hub, p))]
        if not present:
            return
        try:
            os.remove(tmp_index)
        except OSError:
            pass
        # Stage into a throwaway index so main's index and HEAD are untouched.
        git("read-tree", "--empty", use_index=True)
        if git("update-index", "--add", "--", *present,
               use_index=True).returncode != 0:
            return
        tree = git("write-tree", use_index=True).stdout.strip()
        if not tree:
            return
        parent = git("rev-parse", "--verify", "-q",
                     LEDGER_REF + "^{commit}").stdout.strip()
        if parent:
            parent_tree = git("rev-parse", "--verify", "-q",
                              parent + "^{tree}").stdout.strip()
            if parent_tree == tree:
                return  # no change since the last checkpoint
        args = ["commit-tree", tree, "-m", "records: periodic ledger checkpoint"]
        if parent:
            args += ["-p", parent]
        commit = git(*args, use_index=True).stdout.strip()
        if not commit:
            return
        git("update-ref", LEDGER_REF, commit)
    except (OSError, subprocess.SubprocessError):
        pass
    finally:
        try:
            os.remove(tmp_index)
        except OSError:
            pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", default="",
                    help="session id of the just-started session, never touched")
    ap.add_argument("--hub", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="plan the sweep, write nothing and commit nothing")
    args = ap.parse_args(argv)
    hub = args.hub or find_hub()
    if hub is None:
        return 0
    if not acquire_lock(hub):
        return 0
    try:
        sweep(hub, args.current, dry_run=args.dry_run)
        _checkpoint_ledger(hub, dry_run=args.dry_run)
    finally:
        release_lock(hub)
    return 0


if __name__ == "__main__":
    sys.exit(main())
