# nisse

[![CI](https://github.com/chizhangucb/nisse/actions/workflows/ci.yml/badge.svg)](https://github.com/chizhangucb/nisse/actions/workflows/ci.yml)

A starter kit for a personal AI operating system: one git repo your AI assistant lives in, holding your context, your knowledge, and the standards it follows when working for you.

The name: a nisse is the Scandinavian household gnome that quietly does the chores as long as you treat it well. Same deal here.

## The loop

Paste a meeting transcript or a note and say "ingest this".

- **Ingest** mirrors the raw capture, writes a source page with a digest, takeaways, and signals, and queues it.
- **Distill** mines the queue into dated, cited evidence on entity and concept pages. Evidence is append-only: a contradicted claim gets a Superseded note, never an overwrite.
- **Triage** promotes evidence into Current truth, only with your yes, and rotates old evidence to the archive.

The result is a knowledge layer your assistant answers from by citing a durable page, instead of re-deriving your life from scratch every session. That loop is the product. Everything else here is the frame around it.

It runs entirely on the host agent: no API keys, no services.

## Quickstart

```bash
git clone https://github.com/chizhangucb/nisse && cd nisse
claude   # or your harness of choice
```

Install the git guards once per clone, so nothing confidential can be pushed:

```bash
brew install gitleaks                        # the push guard needs it
python3 scripts/guards/install_push_guard.py # pre-push secret + CONFIDENTIAL scan
```

Then fill in `context/` (five short files: who you are, your work, your people, your priorities, your goals) and ingest your first source.

**On Windows:** enable symlinks in git before cloning (`git config --global core.symlinks true`), or `CLAUDE.md` lands as a text file and your assistant reads nothing.

## What it is

Not an app. Markdown, folders, and small scripts an agentic coding harness turns into an operating system. Claude Code is the first-class harness (the skills are Claude Code artifacts); anything that reads `AGENTS.md` can work the repo too.

| Path | What it holds |
|---|---|
| `AGENTS.md` | the map your assistant loads every session. `CLAUDE.md` is a symlink to it |
| `CONTEXT.md` | the glossary: the words this repo uses, and the ones to avoid |
| `context/` | who you are: your work, your people, your priorities, your goals |
| `docs/` | the standards, and the decisions behind why the repo looks the way it does |
| `wiki/` | the knowledge layer, with its own schema in `wiki/AGENTS.md` |
| `projects/` | one folder per workstream |
| `contacts/` | the local contact store |
| `skills/` | the judgment procedures, starting with the wiki loop |
| `scripts/` | the deterministic mechanics behind them, and the git guards in `scripts/guards/` |

## Process skills

For the engineering side (specs, issues, TDD, code review, domain modeling), install [Matt Pocock's skills](https://github.com/mattpocock/skills#installation). They work on Claude Code and other harnesses, and this repo is shaped to match them. Nothing is vendored here.

## One thing to keep

This repo is designed to hold your real life: decisions, meetings, money, people. Keep your instance on a private remote and treat it as private infrastructure. `docs/confidentiality.md` is the standard for what never leaves, marked by a `CONFIDENTIAL` file in any folder that carries it, and the wiki routes anything sensitive to `wiki/confidential/` by default. Fill it in before you feed the system anything real.

## Family

nisse is one of two local-first tools that work on their own:

- **nisse** is the repo your assistant lives in.
- **[Chronicle](https://github.com/chizhangucb/chronicle)** answers what happened in a session, in depth.

## License

Apache-2.0. See [LICENSE](LICENSE).
