#!/usr/bin/env python3
"""PreToolUse deny hook: route all ledger writes through the append command
(CHI-313).

The four ledgers (records/decisions.jsonl, records/sessions.jsonl,
wiki/metadata/log.jsonl, wiki/metadata/sources.jsonl) and the retired markdown
they dual-write through the bake (decisions.md, sessions_index.md, log.md,
sources-*.md, and the *_history shards) are written ONLY through
scripts/aios_ledger.py (the sanctioned append/upsert path). A single serialized
writer is what removes the CHI-299 concurrent-rewrite corruption class, so this
hook blocks the accidental and casual write paths and makes the append command
the obvious one:

  Edit / Write / NotebookEdit whose file_path is a ledger file  -> deny
  Bash that redirects into / sed -i / tee / truncates / cp/mv onto / dd-of / an
  inline interpreter that names a ledger file                    -> deny

This is a strong DEFAULT-PATH enforcer, not an airtight boundary: Bash
obfuscation stays a named residual, exactly as the egress gate documents. What
actually bounds the damage is git history + line-atomic appends + a bad-line-
tolerant reader, not this hook alone. Chi keeps raw-edit as an absolute last
resort (a hook cannot govern her own editor); a stray hand-edit survives because
the reader skips a bad line, and a validated maintenance command handles the
rare correction. Reads (cat / grep / the Read tool) are never blocked.

Contract: PreToolUse hook. Reads the tool call as JSON on stdin, prints a JSON
decision to stdout. On any parse trouble it stays silent (exit 0 = allow), so a
malformed event never wedges the agent.
"""
import json
import os
import re
import sys

# Basenames that identify a guarded ledger file, matched against the basename of
# any path the tool would write. sources-* covers the retired monthly shards.
GUARDED_BASENAMES = {
    "decisions.jsonl", "decisions.md",
    "sessions.jsonl", "sessions_index.md", ".sessions_index.lock",
    "log.jsonl", "log.md",
    "sources.jsonl",
}
# Retired shard families (prefix match on the basename).
GUARDED_PREFIXES = ("sources-",)
# Retired history-shard directories (any .md under them is guarded).
GUARDED_DIR_PARTS = ("decisions_history", "log_history")

DENY_MSG = (
    "Ledger files are append-only and write only through the sanctioned "
    "command (CHI-313). Do not Edit/Write or shell-redirect them. Use:\n"
    "  python3 scripts/aios_ledger.py append-decision "
    "--date YYYY-MM-DD --title '...' --session <id> --stream <aios|kite|...> "
    "--body '- **Decision.** why. -> pointer'\n"
    "  python3 scripts/aios_ledger.py append-log   --date ... --op ... --detail ...\n"
    "  python3 scripts/aios_ledger.py append-source --month YYYY-MM --slug ... --raw ...\n"
    "  python3 scripts/aios_ledger.py upsert-session --session <id> --stamp '...' --repo ...\n"
    "The reader tolerates a stray line, so a genuine emergency hand-edit is "
    "survivable, but it is a last resort, not the write path."
)


def _basename_guarded(path):
    if not path:
        return False
    norm = path.replace("\\", "/")
    base = os.path.basename(norm.rstrip("/"))
    if base in GUARDED_BASENAMES:
        return True
    if any(base.startswith(p) and base.endswith(".md") for p in GUARDED_PREFIXES):
        return True
    parts = set(norm.split("/"))
    if parts & set(GUARDED_DIR_PARTS) and base.endswith(".md"):
        return True
    return False


# Bash tokens that indicate a write to a following/embedded path.
_REDIRECT_RE = re.compile(r">>?\s*(?:['\"]?)([^\s'\"|;&<>()]+)")
# Commands (matched as the SEGMENT's leading command token, not a raw substring,
# so "add" never matches "dd" and git is never mistaken for a mutator) that
# would rewrite a file named in their segment. git is deliberately absent: git
# add/commit/checkout/show stage or restore, they are not the freehand-edit
# vector this guard blocks.
_MUTATOR_CMDS = {"sed", "tee", "dd", "truncate", "cp", "mv", "install",
                 "python", "python2", "python3", "perl", "ruby", "awk"}


def _bash_writes_ledger(command):
    """True if a Bash command would MUTATE a guarded ledger file. Conservative:
    a redirect target that is a ledger file, or a mutator command (by its
    leading token) whose segment names a ledger basename. Reads (cat/grep) and
    git operations that merely name a ledger, with no rewrite, are allowed."""
    if not command:
        return False
    # Split on the usual command separators so `cat a.jsonl > /tmp/x` associates
    # the redirect with /tmp/x, not the ledger being read.
    segments = re.split(r"[;\n]|&&|\|\||\|", command)
    for seg in segments:
        for target in _REDIRECT_RE.findall(seg):
            if _basename_guarded(target):
                return True
        toks = seg.split()
        if not toks:
            continue
        cmd = os.path.basename(toks[0])
        if cmd in _MUTATOR_CMDS and _names_ledger(seg):
            return True
    return False


def _names_ledger(text):
    for base in GUARDED_BASENAMES:
        if base in text:
            return True
    for pre in GUARDED_PREFIXES:
        if re.search(re.escape(pre) + r"[0-9-]*\.md", text):
            return True
    for part in GUARDED_DIR_PARTS:
        if part in text:
            return True
    return False


def _deny():
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": DENY_MSG,
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    if tool in ("Edit", "Write", "NotebookEdit"):
        path = ti.get("file_path") or ti.get("notebook_path") or ""
        if _basename_guarded(path):
            _deny()
            return 0
    elif tool == "Bash":
        if _bash_writes_ledger(ti.get("command") or ""):
            _deny()
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
