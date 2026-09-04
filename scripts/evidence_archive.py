#!/usr/bin/env python3
r"""Evidence archival helper.

Rolls the oldest eligible Evidence bullets from over-budget living wiki pages to
`wiki/archive/<same-subpath>.md`, verbatim, oldest-month-first, until the page is
under its word budget or nothing eligible remains. Promotes the manual `.tmp/`
routine wiki-triage ran 3x (2026-07-29 / 08-01 / 08-03) into a real script.

What it guarantees per page:
- dry-run by default, `--apply` to write.
- conservation: (live Evidence bullets + archive bullets) is identical before and
  after, re-counted from the RENDERED output, never trusted from the plan.
- archive frontmatter carries `type: archive`, `source_page`, and the source page's
  `confidential:` marks propagated verbatim.
- the `> [!note]` pointer atop the live `# Evidence` is regenerated (stale
  bullet-count / date replaced), never left dangling.
- budget target uses `len(text.split())` over the whole file, matching
  `scripts/wiki_check.py` WIKI_PAGE_BUDGET.

Two bugs this script is built to NOT reintroduce (both hit the manual runs):
1. The archive path keeps the `wiki/` prefix: `wiki/entities/x.md` archives to
   `wiki/archive/entities/x.md`, never `archive/entities/x.md`.
2. Frontmatter fields are read with `[ \t]*` (not `\s*`), so an empty
   `confidential:` field does not swallow the following newline and grab the
   next line's value.

Eligibility is mechanical here (the "largely-folded" judgment stays with the owner in
triage): a plain `- YYYY-MM-DD | ...` Evidence bullet dated strictly before the
cutoff, taken from the leading run only. The script stops at the first
`> [!warning]` / `> [!question]` callout interleaved in the bullet stream, so
open or unresolved-Superseded blocks are never rolled off.
"""
import argparse
import os
import re
import sys
from datetime import date

WIKI_PAGE_BUDGET = 2000  # must match wiki_check.WIKI_PAGE_BUDGET
LIVING_DIRS = ("entities", "concepts", "synthesis", "confidential")

BULLET_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) \|")
# bug 2: [ \t]* NOT \s* -- \s* eats the newline on an empty `confidential:` field
FM_FIELD_RE = re.compile(r"^([A-Za-z0-9_]+):[ \t]*(.*)$")
FM_ITEM_RE = re.compile(r"^[ \t]*-[ \t]+(.*)$")
PROTECT_CALLOUT_RE = re.compile(r"^>\s*\[!(warning|question)\]", re.I)
MONTHS = ("", "January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")


# --------------------------------------------------------------------------- #
# frontmatter                                                                  #
# --------------------------------------------------------------------------- #

def parse_frontmatter(text):
    """Leading YAML block -> dict. Scalars/inline lists are strings; block
    lists become Python lists. Uses [ \\t]* so an empty scalar keeps its own
    line (bug 2)."""
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = {}
    key = None
    for line in m.group(1).split("\n"):
        item = FM_ITEM_RE.match(line)
        if item and key is not None:
            if isinstance(fm.get(key), list):
                fm[key].append(item.group(1).strip())
            else:
                fm[key] = [item.group(1).strip()]
            continue
        field = FM_FIELD_RE.match(line)
        if field:
            key = field.group(1)
            fm[key] = field.group(2)  # "" for a bare field; block items may follow
    return fm


def fm_list(fm, key):
    v = fm.get(key)
    if isinstance(v, list):
        return v
    if not v:
        return []
    inner = v.strip()
    if inner.startswith("[") and inner.endswith("]"):
        inner = inner[1:-1]
    return [x.strip() for x in inner.split(",") if x.strip()]


def fm_scalar(fm, key):
    v = fm.get(key)
    return v if isinstance(v, str) else None


# --------------------------------------------------------------------------- #
# paths                                                                        #
# --------------------------------------------------------------------------- #

def archive_path_for(living_rel):
    """`wiki/entities/x.md` -> `wiki/archive/entities/x.md` (bug 1: keep wiki/)."""
    rel = living_rel[len("wiki/"):] if living_rel.startswith("wiki/") else living_rel
    return os.path.join("wiki", "archive", rel)


def archive_link_target(living_rel):
    """`wiki/entities/x.md` -> `archive/entities/x` (wikilink target, no ext)."""
    rel = living_rel[len("wiki/"):] if living_rel.startswith("wiki/") else living_rel
    if rel.endswith(".md"):
        rel = rel[:-3]
    return "archive/" + rel


def page_slug(living_rel):
    base = os.path.basename(living_rel)
    return base[:-3] if base.endswith(".md") else base


# --------------------------------------------------------------------------- #
# evidence parsing                                                             #
# --------------------------------------------------------------------------- #

def split_evidence(page):
    """Return (head, ev_region, tail): head ends with the `# Evidence` heading
    line, ev_region is the body of that section, tail is any later heading."""
    m = re.search(r"(?m)^# Evidence[^\n]*\n", page)
    if not m:
        return page, None, ""
    head = page[:m.end()]
    rest = page[m.end():]
    nxt = re.search(r"(?m)^#{1,6} ", rest)
    if nxt:
        return head, rest[:nxt.start()], rest[nxt.start():]
    return head, rest, ""


def parse_ev_region(ev_region):
    """Split an Evidence body into (existing pointer text, ordered blocks).

    Every `> [!note]` archived-evidence pointer is regenerable scaffolding: they
    are captured (first one returned) and stripped from the block list, wherever
    they sit -- top OR stranded mid-Evidence after a prior partial archival (the
    stale-mid-pointer case calls out). Remaining blocks are bullets
    (`- YYYY-MM-DD | ...`, with continuations) or protective `> [!warning]` /
    `> [!question]` callouts. Blank lines are dropped, re-inserted on render."""
    lines = ev_region.split("\n")
    blocks = []
    cur = None
    for line in lines:
        bm = BULLET_RE.match(line)
        if bm:
            cur = {"type": "bullet", "date": bm.group(1), "lines": [line]}
            blocks.append(cur)
        elif line.startswith(">"):
            if cur and cur["type"] in ("callout", "note"):
                cur["lines"].append(line)
            else:
                is_note = bool(re.match(r"^>\s*\[!note\]", line, re.I))
                cur = {"type": "note" if is_note else "callout",
                       "date": None, "lines": [line]}
                blocks.append(cur)
        elif line.strip() == "":
            cur = None  # blank line ends the current block
        else:
            if cur is not None:
                cur["lines"].append(line)  # continuation of the current block
            # a stray line with no owner is dropped

    pointer = next(("\n".join(b["lines"]) for b in blocks if b["type"] == "note"),
                   None)
    blocks = [b for b in blocks if b["type"] != "note"]
    return pointer, blocks


def leading_movable(blocks, cutoff):
    """Bullets from the leading run (before any protective callout) dated
    strictly before cutoff, oldest-first (evidence is already date-ascending)."""
    movable = []
    for b in blocks:
        if b["type"] == "callout":
            break  # stop at the first warning/question -> never roll it off
        if b["type"] != "bullet":
            continue
        if parse_iso(b["date"]) < cutoff:
            movable.append(b)
        else:
            break  # ascending order: once we pass the cutoff we are done
    return movable


def parse_iso(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


# --------------------------------------------------------------------------- #
# rendering                                                                    #
# --------------------------------------------------------------------------- #

def render_live(head, tail, pointer_line, remaining_blocks):
    body_lines = []
    if pointer_line:
        body_lines.append(pointer_line)
        body_lines.append("")
    for b in remaining_blocks:
        body_lines.extend(b["lines"])
    ev_body = "\n".join(body_lines).rstrip("\n")
    out = head
    if not out.endswith("\n"):
        out += "\n"
    out += "\n" + ev_body + "\n"
    if tail:
        out += tail
    return out


def build_pointer(archive_target, archive_bullet_count, cutoff, today):
    month = MONTHS[cutoff.month]
    return (f"> [!note] Pre-{month} Evidence ({archive_bullet_count} bullets) "
            f"rotated to [[{archive_target}|archived evidence]], last updated "
            f"{today.isoformat()} (folded, older than a month). Later evidence "
            f"below.")


def render_confidential(conf):
    if not conf:
        return "confidential:"
    return "confidential: [" + ", ".join(conf) + "]"


def build_archive(source_fm, living_rel, moved_blocks, today):
    """Fresh archive file text with frontmatter, intro, and the moved bullets."""
    slug = page_slug(living_rel)
    title = slug.replace("_", " ")
    tags = fm_list(source_fm, "tags")[:2]
    project = fm_scalar(source_fm, "project") or "work"
    conf = fm_list(source_fm, "confidential")
    fm_lines = [
        "---",
        "type: archive",
        "tags: [" + ", ".join(tags) + "]",
        f"project: {project}",
        render_confidential(conf),
        f"created: {today.isoformat()}",
        f"source_page: [[{slug}]]",
        "---",
    ]
    intro = (f"# {title} (archived evidence)\n\n"
             f"Rolled-off Evidence from [[{slug}]], oldest first, folded into "
             f"that page's Current truth. Append-only ledger kept for "
             f"provenance, not maintained as living knowledge. See the live "
             f"page for current state.\n\n# Evidence (archived)\n")
    bullets = "\n".join("\n".join(b["lines"]) for b in moved_blocks)
    return "\n".join(fm_lines) + "\n\n" + intro + "\n" + bullets + "\n"


def count_archive_bullets(archive_text):
    if archive_text is None:
        return 0
    return sum(1 for ln in archive_text.split("\n") if BULLET_RE.match(ln))


def append_to_archive(archive_text, moved_blocks):
    bullets = "\n".join("\n".join(b["lines"]) for b in moved_blocks)
    return archive_text.rstrip("\n") + "\n" + bullets + "\n"


# --------------------------------------------------------------------------- #
# core                                                                         #
# --------------------------------------------------------------------------- #

class ArchiveError(Exception):
    pass


def plan_page(root, living_rel, cutoff, budget, today):
    """Compute the archival for one page. Returns a dict describing the plan;
    does not write. Raises ArchiveError on a conservation failure."""
    living_abs = os.path.join(root, living_rel)
    with open(living_abs, encoding="utf-8") as f:
        page = f.read()

    fm = parse_frontmatter(page)
    head, ev_region, tail = split_evidence(page)
    if ev_region is None:
        raise ArchiveError(f"{living_rel}: no # Evidence section")

    pointer, blocks = parse_ev_region(ev_region)
    live_bullets_before = [b for b in blocks if b["type"] == "bullet"]

    archive_rel = archive_path_for(living_rel)
    archive_abs = os.path.join(root, archive_rel)
    archive_text = None
    if os.path.exists(archive_abs):
        with open(archive_abs, encoding="utf-8") as f:
            archive_text = f.read()
    archive_bullets_before = count_archive_bullets(archive_text)
    total_before = len(live_bullets_before) + archive_bullets_before

    movable = leading_movable(blocks, cutoff)
    archive_target = archive_link_target(living_rel)

    # move oldest-first until under budget, or all movable exhausted
    def render_with(k):
        moved = movable[:k]
        remaining = [b for b in blocks if b not in moved]
        if k > 0:
            ptr = build_pointer(archive_target, archive_bullets_before + k, cutoff, today)
        else:
            ptr = pointer  # nothing moved -> leave existing pointer untouched
        return render_live(head, tail, ptr, remaining)

    start_words = len(page.split())
    chosen = 0
    for k in range(0, len(movable) + 1):
        chosen = k
        if len(render_with(k).split()) <= budget:
            break

    moved = movable[:chosen]
    new_live = render_with(chosen)
    end_words = len(new_live.split())

    # build the new archive
    if chosen == 0:
        new_archive = archive_text
    elif archive_text is None:
        new_archive = build_archive(fm, living_rel, moved, today)
    else:
        new_archive = append_to_archive(archive_text, moved)

    # conservation, re-counted from the RENDERED text (never trusted from plan)
    _, new_ev, _ = split_evidence(new_live)
    _, new_blocks = parse_ev_region(new_ev)
    live_after = sum(1 for b in new_blocks if b["type"] == "bullet")
    archive_after = count_archive_bullets(new_archive)
    total_after = live_after + archive_after
    if total_after != total_before:
        raise ArchiveError(
            f"{living_rel}: conservation FAILED "
            f"(before {total_before} = live {len(live_bullets_before)} + archive "
            f"{archive_bullets_before}; after {total_after} = live {live_after} + "
            f"archive {archive_after})")
    if live_after != len(live_bullets_before) - len(moved):
        raise ArchiveError(f"{living_rel}: live bullet delta mismatch")

    return {
        "living_rel": living_rel,
        "archive_rel": archive_rel,
        "archive_created": chosen > 0 and archive_text is None,
        "moved": len(moved),
        "start_words": start_words,
        "end_words": end_words,
        "budget": budget,
        "under_budget": end_words <= budget,
        "movable": len(movable),
        "total_bullets": total_before,
        "new_live": new_live,
        "new_archive": new_archive,
        "confidential": fm_list(fm, "confidential"),
    }


def discover_pages(root, cutoff, budget):
    """Living pages over budget with at least one eligible bullet."""
    found = []
    for d in LIVING_DIRS:
        base = os.path.join(root, "wiki", d)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not name.endswith(".md"):
                continue
            rel = os.path.join("wiki", d, name)
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                if len(f.read().split()) > budget:
                    found.append(rel)
    return found


def default_cutoff(today):
    y, m = today.year, today.month - 1
    if m == 0:
        y, m = y - 1, 12
    return date(y, m, 1)


def run(root, pages, cutoff, budget, apply, today, out=sys.stdout):
    if not pages:
        pages = discover_pages(root, cutoff, budget)
        if not pages:
            print("no over-budget living pages; nothing to archive.", file=out)
            return 0

    exit_code = 0
    for rel in pages:
        try:
            plan = plan_page(root, rel, cutoff, budget, today)
        except (ArchiveError, OSError) as e:
            print(f"FAIL {e}", file=out)
            exit_code = 1
            continue

        tag = "apply" if apply else "dry-run"
        note = ""
        if plan["moved"] == 0:
            note = " (nothing to do: under budget or nothing eligible)"
        elif not plan["under_budget"]:
            note = " (STILL over budget: eligible evidence exhausted)"
        archive_tag = " +new archive" if plan["archive_created"] else ""
        print(f"[{tag}] {rel}: move {plan['moved']}/{plan['movable']} eligible "
              f"-> {plan['archive_rel']}{archive_tag}; "
              f"{plan['start_words']}w -> {plan['end_words']}w "
              f"(budget {plan['budget']}); conservation OK "
              f"({plan['total_bullets']} bullets){note}", file=out)

        if apply and plan["moved"] > 0:
            archive_abs = os.path.join(root, plan["archive_rel"])
            os.makedirs(os.path.dirname(archive_abs), exist_ok=True)
            with open(archive_abs, "w", encoding="utf-8") as f:
                f.write(plan["new_archive"])
            with open(os.path.join(root, plan["living_rel"]), "w",
                      encoding="utf-8") as f:
                f.write(plan["new_live"])
    return exit_code


def main(argv=None, root=None, today=None):
    ap = argparse.ArgumentParser(description="Roll folded Evidence to wiki/archive/.")
    ap.add_argument("pages", nargs="*",
                    help="living page paths (wiki/entities/x.md); default: "
                         "auto-discover over-budget pages")
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run)")
    ap.add_argument("--before", metavar="YYYY-MM-DD",
                    help="cutoff; bullets strictly before it are eligible "
                         "(default: first day of last month)")
    ap.add_argument("--budget", type=int, default=WIKI_PAGE_BUDGET,
                    help=f"word budget (default {WIKI_PAGE_BUDGET})")
    ap.add_argument("--root", default=root or os.getcwd())
    args = ap.parse_args(argv)

    today = today or date.today()
    cutoff = parse_iso(args.before) if args.before else default_cutoff(today)
    return run(args.root, list(args.pages), cutoff, args.budget, args.apply, today)


if __name__ == "__main__":
    sys.exit(main())
