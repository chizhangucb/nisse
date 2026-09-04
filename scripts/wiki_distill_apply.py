#!/usr/bin/env python3
"""Mechanical write step for wiki-distill (Phase 1, lever 2).

Today, after the owner approves a distill checkpoint package, the agent hand-edits
every touched page: inserts evidence bullets, fills each source's
`# Distilled` section, stamps `distilled:`, mints tags, appends the log line.
That is pure mechanics once the package is approved (the judgment already
happened at draft/checkpoint time) but it currently burns frontier-agent Edit
calls per line. This script takes the already-approved package as JSON and
does the writing deterministically.

Scope v1: EXISTING pages only. Creating a brand-new entity/concept/synthesis
page still needs the agent (subtype, wording, inbound links are judgment);
route those through the normal skill flow and only hand already-existing-page
updates to this script.

Package shape (see PACKAGE_EXAMPLE below):
  {
    "date": "2026-08-17",
    "updates": [
      {"page": "wiki/entities/foo.md",
       "bullets": ["- 2026-08-17 | claim | #tag | Source: [[sources/2026-08-17_x]] (primary)"],
       "source_slug": "2026-08-17_x"}
    ],
    "distilled_lines": {
      "2026-08-17_x": ["- [[entities/foo]] | Evidence +1 | one line of what landed"]
    },
    "tags_to_mint": [
      {"section": "work", "slug": "foo_tag", "aliases": "", "description": "..."}
    ],
    "log_line": "- 2026-08-17 | distill | ..."
  }

Bullets are validated against the house format (imported from
wiki_check) before anything is written; a bad bullet aborts the
whole run, nothing partially applied.

Usage:
  python3 scripts/wiki_distill_apply.py package.json              # dry-run, prints the diff
  python3 scripts/wiki_distill_apply.py package.json --write       # applies it
  python3 scripts/wiki_distill_apply.py package.json --write --force-stamp
"""

import argparse
import importlib.util
import json
import os
import re
import sys

import wiki_ledger  # append the wiki log to log.jsonl

DEFAULT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)

PACKAGE_EXAMPLE = """{
  "date": "2026-08-17",
  "updates": [{"page": "wiki/entities/foo.md",
               "bullets": ["- 2026-08-17 | claim | #tag | Source: [[sources/x]] (primary)"],
               "source_slug": "2026-08-17_x"}],
  "distilled_lines": {"2026-08-17_x": ["- [[entities/foo]] | Evidence +1 | one line landed"]},
  "tags_to_mint": [],
  "log_line": "- 2026-08-17 | distill | ..."
}"""


def _load_check_module():
    """Import wiki_check.py (no hyphens, so a normal import would work if
    scripts/ were a package; it is not, so load by path instead). The wiki
    checker exposes the evidence-bullet house format this script writes to."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wiki_check.py")
    spec = importlib.util.spec_from_file_location("wiki_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK = _load_check_module()

# wiki/metadata/log.md house format (wiki-triage/references/triage-rules.md):
# `- YYYY-MM-DD | type | ...`. A missing leading "- " is auto-fixed (the one
# unambiguous, deterministic gap); anything else -- no type field, no pipes at
# all -- refuses the whole write rather than landing a line hygiene has to
# catch after the fact (this omission was the actual root cause of a
# ~620-line log.md corruption, traced to package authors copying this script's
# own log_line docstring example, which itself lacked the dash).
LOG_LINE_RE = re.compile(r"^- \d{4}-\d{2}-\d{2} \| [^|]+ \| .+$")


def resolve_root(cli_root):
    if cli_root:
        return os.path.abspath(cli_root)
    env = os.environ.get("AIOS_ROOT")
    if env:
        return os.path.abspath(env)
    return DEFAULT_ROOT


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Evidence insertion
# ---------------------------------------------------------------------------


def insert_evidence_bullets(text, new_bullets, path_for_errors):
    """Insert new_bullets into the `# Evidence` section, ascending date order.

    Existing bullets never move relative to each other; a new bullet is
    placed at the first position whose existing-bullet date is >= its own
    date (stable insert), or at the end of the section if none is later.
    Raises ValueError (never guesses) if there is no `# Evidence` heading.
    """
    lines = text.split("\n")
    heading_idx = None
    for i, line in enumerate(lines):
        if line.strip() == CHECK.EVIDENCE_HEADING:
            heading_idx = i
            break
    if heading_idx is None:
        raise ValueError(
            "%s has no `# Evidence` heading; this is a new-page case, out of "
            "v1 scope for wiki_distill_apply (needs the skill's judgment "
            "scaffold, not the mechanical apply step)" % path_for_errors
        )

    # Section body: heading_idx+1 up to the next top-level `# ` heading or EOF.
    body_start = heading_idx + 1
    body_end = len(lines)
    for i in range(body_start, len(lines)):
        if lines[i].startswith("# "):
            body_end = i
            break

    body = lines[body_start:body_end]

    # A trailing "" in body is the split() artifact of the file's final
    # newline (or the section's trailing blank line before the next
    # heading), not a real blank line between bullets. Strip it before
    # inserting and restore the same count after, so insertion never
    # fabricates a blank line between two bullets.
    trailing_blanks = 0
    while body and body[-1] == "":
        body.pop()
        trailing_blanks += 1

    def bullet_date(b):
        m = CHECK.DATED_BULLET_RE.match(b)
        return b[2:12] if m else None

    for nb in new_bullets:
        m = CHECK.BULLET_RE.match(nb)
        if not m:
            raise ValueError(
                "bullet does not match house format, refusing to insert: %r" % nb
            )
        # Idempotent re-insert: an identical bullet already in the section is not
        # duplicated. This makes a distill re-run safe after a mid-write crash
        # left a source's evidence written but its distilled: stamp unset
        # (item 1) -- the source re-lands, the bullet does not double.
        if nb in body:
            continue
        nb_date = m.group("date")
        insert_at = len(body)
        for i, existing in enumerate(body):
            if not existing.startswith("- "):
                continue
            ed = bullet_date(existing)
            if ed and ed >= nb_date:
                insert_at = i
                break
        body.insert(insert_at, nb)

    body.extend([""] * trailing_blanks)
    new_lines = lines[:body_start] + body + lines[body_end:]
    return "\n".join(new_lines)


def ensure_source_in_frontmatter(text, source_slug):
    """Append source_slug to the page's `sources:` frontmatter list if absent."""
    span = CHECK.frontmatter_lines(text)
    if span is None:
        return text  # no frontmatter, nothing to touch (defensive, unlikely)
    lines = text.split("\n")
    for i in range(span[0], span[1]):
        if lines[i].startswith("sources:"):
            raw = lines[i][len("sources:"):].strip()
            if source_slug in raw:
                return text  # already present
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1].strip()
                new_inner = (inner + ", " + source_slug) if inner else source_slug
                lines[i] = "sources: [%s]" % new_inner
            elif raw == "":
                lines[i] = "sources: [%s]" % source_slug
            else:
                lines[i] = "sources: [%s, %s]" % (raw, source_slug)
            return "\n".join(lines)
    return text  # no sources: field on this page type, leave alone


# ---------------------------------------------------------------------------
# Distilled fill + stamp
# ---------------------------------------------------------------------------

DISTILLED_HEADING = "# Distilled"
NO_UPDATES_LINE = "(No durable updates.)"


def fill_distilled(text, new_lines):
    lines = text.split("\n")
    heading_idx = None
    for i, line in enumerate(lines):
        if line.strip() == DISTILLED_HEADING:
            heading_idx = i
            break
    if heading_idx is None:
        # Append the section at EOF, matching the template's placement.
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(DISTILLED_HEADING)
        lines.append("")
        lines.extend(new_lines)
        if not lines or lines[-1] != "":
            lines.append("")
        return "\n".join(lines)

    body_start = heading_idx + 1
    body_end = len(lines)
    for i in range(body_start, len(lines)):
        if lines[i].startswith("# "):
            body_end = i
            break
    body = lines[body_start:body_end]

    # Same split() artifact as insert_evidence_bullets: the section's
    # trailing blank line(s) (EOF newline, or the gap before the next
    # heading) are not content and must round-trip untouched. The template's
    # single leading blank right after the heading is likewise structural,
    # not content, and is preserved separately from it.
    trailing_blanks = 0
    while body and body[-1] == "":
        body.pop()
        trailing_blanks += 1

    had_leading_blank = bool(body) and body[0].strip() == ""
    if had_leading_blank:
        body.pop(0)

    content = [b for b in body if b.strip() and b.strip() != NO_UPDATES_LINE]
    content.extend(new_lines)

    new_body = (([""] if had_leading_blank else [])
                + content
                + ([""] * trailing_blanks))
    new_lines = lines[:body_start] + new_body + lines[body_end:]
    return "\n".join(new_lines)


def stamp_distilled_date(text, date, force):
    span = CHECK.frontmatter_lines(text)
    if span is None:
        raise ValueError("no frontmatter block")
    lines = text.split("\n")
    idx = None
    for i in range(span[0], span[1]):
        if lines[i].startswith("distilled:"):
            idx = i
            break
    if idx is None:
        raise ValueError("no distilled: field")
    existing = lines[idx][len("distilled:"):].strip()
    if existing and not force:
        raise ValueError("already distilled %s (pass --force-stamp to overwrite)" % existing)
    lines[idx] = "distilled: " + date
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tag registry
# ---------------------------------------------------------------------------


def mint_tag(text, section, slug, aliases, description):
    lines = text.split("\n")
    section_heading = "## " + section
    sec_idx = None
    for i, line in enumerate(lines):
        if line.strip() == section_heading:
            sec_idx = i
            break
    if sec_idx is None:
        raise ValueError("no `## %s` section in tag_registry.md" % section)

    # Already present anywhere in this section's table? Skip silently (idempotent).
    end = len(lines)
    for i in range(sec_idx + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    table_rows = [i for i in range(sec_idx, end) if lines[i].startswith("|")]
    for i in table_rows:
        cells = [c.strip() for c in lines[i].strip("|").split("|")]
        if cells and cells[0] == slug:
            return "\n".join(lines)  # already minted

    if not table_rows:
        raise ValueError("no table found under `## %s`" % section)
    last_row = table_rows[-1]
    new_row = "| %s | %s | %s |" % (slug, aliases, description)
    lines.insert(last_row + 1, new_row)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_plan(root, package):
    """Compute every (path, new_text) write without touching disk yet."""
    writes = {}  # abs path -> new text (chained across steps)

    def current(path):
        if path in writes:
            return writes[path]
        text = read(path)
        return text

    date = package["date"]

    for upd in package.get("updates", []):
        abspath = os.path.join(root, upd["page"])
        if not os.path.isfile(abspath):
            raise ValueError("no such page: %s" % upd["page"])
        text = current(abspath)
        text = insert_evidence_bullets(text, upd["bullets"], upd["page"])
        if upd.get("source_slug"):
            text = ensure_source_in_frontmatter(text, upd["source_slug"])
        writes[abspath] = text

    for slug, dlines in package.get("distilled_lines", {}).items():
        src_path = os.path.join(root, "wiki", "sources", slug + ".md")
        if not os.path.isfile(src_path):
            raise ValueError("no such source page: %s" % slug)
        text = current(src_path)
        text = fill_distilled(text, dlines)
        text = stamp_distilled_date(text, date, force=package.get("_force_stamp", False))
        writes[src_path] = text

    for tag in package.get("tags_to_mint", []):
        reg_path = os.path.join(root, "wiki", "metadata", "tag_registry.md")
        text = current(reg_path)
        text = mint_tag(
            text, tag["section"], tag["slug"], tag.get("aliases", ""), tag.get("description", "")
        )
        writes[reg_path] = text

    if package.get("log_line"):
        line = package["log_line"].strip()
        if not line.startswith("- "):
            line = "- " + line  # the one unambiguous, deterministic gap
        if not LOG_LINE_RE.match(line):
            raise ValueError(
                "log_line does not match the house format "
                "'- YYYY-MM-DD | type | ...', refusing to write: %r"
                % package["log_line"]
            )
        # the wiki log is now the append-only wiki/metadata/log.jsonl.
        # Validation stays here (LOG_LINE_RE); the plan carries a parsed ROW
        # under the jsonl path and cmd_run appends it via wiki_ledger rather
        # than rewriting a markdown file.
        m = re.match(r"^- (\d{4}-\d{2}-\d{2}) \| ([^|]+) \| (.+)$", line)
        log_path = os.path.join(root, "wiki", "metadata", "log.jsonl")
        writes[log_path] = {"date": m.group(1), "op": m.group(2).strip(),
                            "detail": m.group(3).strip()}

    return writes


def cmd_run(args):
    root = resolve_root(args.root)
    with open(args.package, encoding="utf-8") as fh:
        package = json.load(fh)
    if args.force_stamp:
        package["_force_stamp"] = True

    try:
        writes = build_plan(root, package)
    except ValueError as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1

    for path in sorted(writes):
        rel = os.path.relpath(path, root)
        after = writes[path]
        if isinstance(after, dict):  # the appended log.jsonl row
            print("%s: +1 row (%s)" % (rel, after.get("op", "")))
            continue
        before = read(path) if os.path.exists(path) else ""
        added = len(after) - len(before)
        print("%s: %s%d bytes" % (rel, "+" if added >= 0 else "", added))

    if not args.write:
        print("\ndry-run only; pass --write to apply (%d file(s))" % len(writes))
        return 0

    for path, text in writes.items():
        if isinstance(text, dict):  # append the wiki-log row
            wiki_ledger.append_wiki_log(root, date=text["date"],
                                        op=text["op"], detail=text["detail"])
        else:
            write(path, text)

    # Self-check: re-validate every touched entity/concept/synthesis/confidential
    # page's Evidence section. Defense in depth, not a substitute for the
    # bullet-format check already run before insertion.
    violations = []
    for path in writes:
        rel = os.path.relpath(path, root)
        if os.path.sep + "sources" + os.path.sep in path:
            continue
        CHECK.check_file(path, rel, violations)
    if violations:
        print("\nWARNING: post-write check found violations:", file=sys.stderr)
        for v in violations:
            print("  %s:%d %s" % (v["file"], v["line"], v["problem"]), file=sys.stderr)

    print("\napplied %d file(s)." % len(writes))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("package", help="path to the approved distill package JSON")
    parser.add_argument("--write", action="store_true", help="apply (default is dry-run)")
    parser.add_argument("--force-stamp", action="store_true",
                        help="overwrite an existing distilled: date")
    parser.add_argument("--root", default=None, help="repo root holding wiki/")
    parser.set_defaults(func=cmd_run)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
