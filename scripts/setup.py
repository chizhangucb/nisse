#!/usr/bin/env python3
"""First-run setup: personalize the floor and check the toolchain.

Idempotent; run it again any time. Does four things, tells you what it did:

1. Toolchain check: python3 version, git, and (warn-only) the `claude` CLI.
2. Floor integrity: CLAUDE.md / AGENTS.md / GEMINI.md must be symlinks to
   AIOS.md (a Windows clone without symlinks gets real copies instead).
3. Personalization: asks your name (skippable) and writes it into the AIOS.md
   opening line, so every session starts addressed to you.
4. `.env` from `.env.example` if absent (connector keys, all optional).

It never touches governance/, context/ content, or the wiki: those are yours
to customize by hand (start with governance/README.md).
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOOR = "AIOS.md"
SYMLINKS = ("CLAUDE.md", "AGENTS.md", "GEMINI.md")
PLACEHOLDER = "the owner's personal AIOS"


def ok(msg):
    print(f"  [ok] {msg}")


def warn(msg):
    print(f"  [!!] {msg}")


def check_toolchain():
    print("Toolchain:")
    if sys.version_info < (3, 9):
        warn(f"python {sys.version.split()[0]} is old; 3.9+ recommended")
    else:
        ok(f"python {sys.version.split()[0]}")
    for tool, required in (("git", True), ("claude", False)):
        if shutil.which(tool):
            ok(tool)
        elif required:
            warn(f"{tool} not found; install it before going further")
        else:
            warn(f"{tool} CLI not found. The wiki loop and hooks are Claude "
                 "Code artifacts; any harness that reads AGENTS.md still works, "
                 "but the shipped skills expect Claude Code.")


def check_floor():
    print("Floor:")
    floor_path = os.path.join(ROOT, FLOOR)
    if not os.path.exists(floor_path):
        warn(f"{FLOOR} missing; re-clone or restore it, nothing works without "
             "the map")
        return
    for name in SYMLINKS:
        p = os.path.join(ROOT, name)
        if os.path.islink(p):
            ok(f"{name} -> {FLOOR}")
            continue
        # Missing, or a real file from a symlink-less clone: (re)create as a
        # symlink where possible, else copy content so parity holds.
        try:
            if os.path.exists(p):
                os.remove(p)
            os.symlink(FLOOR, p)
            ok(f"{name} -> {FLOOR} (created)")
        except OSError:
            shutil.copyfile(floor_path, p)
            ok(f"{name} copied from {FLOOR} (symlinks unavailable; re-run "
               "setup after editing the floor to keep them in sync)")

    # .claude/skills must point at ../skills or the harness sees no skills.
    sk = os.path.join(ROOT, ".claude", "skills")
    if os.path.islink(sk) or os.path.isdir(sk):
        ok(".claude/skills -> ../skills")
    else:
        try:
            os.symlink(os.path.join("..", "skills"), sk)
            ok(".claude/skills -> ../skills (created)")
        except OSError:
            warn(".claude/skills symlink missing and could not be created "
                 "(symlink-less filesystem?): copy the skills/ folder to "
                 ".claude/skills yourself or the shipped skills won't load")


def personalize():
    print("Personalization:")
    floor_path = os.path.join(ROOT, FLOOR)
    try:
        with open(floor_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return
    if PLACEHOLDER not in text:
        ok("floor already personalized")
        return
    try:
        name = input("  Your name (enter to skip): ").strip()
    except EOFError:
        name = ""
    if not name:
        ok("skipped; edit AIOS.md yourself when ready")
        return
    text = text.replace(PLACEHOLDER, f"{name}'s personal AIOS", 1)
    with open(floor_path, "w", encoding="utf-8") as f:
        f.write(text)
    ok(f"AIOS.md now opens addressed to {name}")


def ensure_env():
    print("Env:")
    env = os.path.join(ROOT, ".env")
    example = os.path.join(ROOT, ".env.example")
    if os.path.exists(env):
        ok(".env exists")
    elif os.path.exists(example):
        shutil.copyfile(example, env)
        ok(".env created from .env.example (all keys optional; tier 1 needs "
           "none)")
    else:
        warn(".env.example missing; connectors are documented in operations.md")


def next_steps():
    print("""
Next steps:
  1. Customize governance/communication-style.md and
     governance/confidentiality.md (see governance/README.md for what's
     structure vs yours).
  2. Fill in context/ (about-me, about-business, about-team, priorities).
  3. Start a session (`claude`) and try the magic moment: paste any meeting
     transcript or note and say "ingest this". Then "distill", then "triage".
  4. Optional, later: connectors in operations.md (tier 2) and the dormant
     tier-3 components (egress gate, routing, graphs), each with its own
     wiring guide.
""")


def main():
    print(f"nisse setup, repo: {ROOT}\n")
    check_toolchain()
    check_floor()
    personalize()
    ensure_env()
    next_steps()
    return 0


if __name__ == "__main__":
    sys.exit(main())
