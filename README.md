# nisse

[![CI](https://github.com/chizhangucb/nisse/actions/workflows/ci.yml/badge.svg)](https://github.com/chizhangucb/nisse/actions/workflows/ci.yml)

A starter kit for a personal AI operating system: one git repo your AI assistant lives in, holding your context, your knowledge, and the standards it follows when working for you.

Not an app. Markdown, folders, and small scripts an agentic coding harness turns into an operating system. No API keys, no services. Claude Code is the first-class harness; anything that reads `AGENTS.md` can work the repo too.

## The loop

Paste a meeting transcript or a note and say "ingest this".

- **Ingest** mirrors the raw capture, writes a source page with a digest, takeaways, and signals, and queues it.
- **Distill** mines the queue into dated, cited evidence on entity and concept pages. Evidence is append-only: a contradicted claim gets a Superseded note, never an overwrite.
- **Triage** promotes evidence into Current truth, only with your yes, and rotates old evidence to the archive.

You get a knowledge layer your assistant answers from by citing a durable page, instead of re-deriving your life every session. That loop is the product. Everything else is frame around it.

## Quickstart

```bash
git clone https://github.com/chizhangucb/nisse && cd nisse
brew install gitleaks                        # the push guard needs it
python3 scripts/guards/install_push_guard.py # pre-push secret + CONFIDENTIAL scan
claude   # or your harness of choice
```

Then fill in `context/` (who you are, your work, your people, your priorities, your goals) and ingest your first source.

**On Windows:** enable symlinks before cloning (`git config --global core.symlinks true`), or `CLAUDE.md` lands as a text file and your assistant reads nothing.

## The map

`AGENTS.md` is what your assistant loads every session, and it names the rest: `CONTEXT.md` (the glossary), `context/`, `wiki/`, `projects/`, `contacts/`, `skills/`, `scripts/`, `docs/`.

## Privacy

This repo is designed to hold your real life: decisions, meetings, money, people. Keep your instance on a private remote. `docs/confidentiality.md` is the standard for what never leaves, marked by a `CONFIDENTIAL` file in any folder that carries it, and the wiki routes anything sensitive to `wiki/confidential/` by default. Fill it in before you feed the system anything real.

## Also

- For the engineering side (specs, issues, TDD, code review), install [Matt Pocock's skills](https://github.com/mattpocock/skills#installation). This repo is shaped to match them; nothing is vendored here.
- [Chronicle](https://github.com/chizhangucb/chronicle), the sibling tool, answers what happened in a session.

Apache-2.0. See [LICENSE](LICENSE).
