#!/usr/bin/env python3
"""Stop-hook: tidy this session's own decision block in records/decisions.md.

Mechanical consolidation only, worst case cosmetic:
- inside blocks whose header carries this session's short id AND today's date,
  drop exact-duplicate "- Decision:" lines, keeping the first;
- collapse runs of 3 or more blank lines to one;
- make sure the file ends with a newline.

Never touches another session's block or another day's block, never reorders,
never rewrites wording. Any anomaly is a silent no-op.
"""
import sys, json, datetime, re, os

BLOCK_RE = re.compile(r"^##\s*(\d{4}-\d{2}-\d{2})\s*:.*\(session\s+([0-9A-Za-z]+)",
                      re.IGNORECASE)


def main():
    # A headless subsession never owns a decision block; skip it so a spawned
    # child session cannot rewrite the log.
    if os.environ.get("AIOS_CLOSE_SUBSESSION"):
        return 0
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    sid = (data.get("session_id") or "").strip()
    cwd = (data.get("cwd") or "").strip()
    if not sid or not cwd:
        return 0

    path = f"{cwd}/records/decisions.md"
    try:
        with open(path) as f:
            original = f.read()
    except OSError:
        return 0

    short = sid[:8].lower()
    today = datetime.date.today().isoformat()
    lines = original.splitlines()

    try:
        out = _consolidate(lines, short, today)
    except Exception:
        return 0

    text = "\n".join(out).rstrip("\n") + "\n"
    if text != original:
        try:
            with open(path, "w") as f:
                f.write(text)
        except OSError:
            return 0
    return 0


def _mine(line, short, today):
    """True when this header line opens a block owned by this session today."""
    m = BLOCK_RE.match(line.strip())
    if not m:
        return False
    return m.group(1) == today and m.group(2).lower().startswith(short)


def _consolidate(lines, short, today):
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not (line.lstrip().startswith("## ") and _mine(line, short, today)):
            out.append(line)
            i += 1
            continue
        # Own block: runs to the next "## " header or end of file.
        end = i + 1
        while end < n and not lines[end].lstrip().startswith("## "):
            end += 1
        out.append(line)
        out.extend(_clean_block(lines[i + 1:end]))
        i = end
    return out


def _clean_block(body):
    seen = set()
    cleaned = []
    for line in body:
        stripped = line.strip()
        # One-line format: a decision is `- **Decision.** why. -> pointer`.
        # (Older blocks used `- Decision:`; keep deduping those too.)
        if stripped.startswith("- **") or stripped.startswith("- Decision:"):
            if stripped in seen:
                continue
            seen.add(stripped)
        cleaned.append(line)
    return _collapse_blanks(cleaned)


def _collapse_blanks(body):
    out = []
    blanks = 0
    for line in body:
        if line.strip() == "":
            blanks += 1
            continue
        if blanks:
            out.extend([""] * (1 if blanks >= 3 else blanks))
            blanks = 0
        out.append(line)
    if blanks:
        out.extend([""] * (1 if blanks >= 3 else blanks))
    return out


if __name__ == "__main__":
    sys.exit(main())
