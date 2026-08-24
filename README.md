# nisse

[![CI](https://github.com/chizhangucb/nisse/actions/workflows/ci.yml/badge.svg)](https://github.com/chizhangucb/nisse/actions/workflows/ci.yml)

A starter kit for a personal AI operating system: a plain-files git repo your AI assistant lives in, with the folder taxonomy, written governance, append-only records, and knowledge loops to help you think, decide, and ship.

The name: a nisse is the Scandinavian household gnome that quietly does the chores as long as you treat it well. Same deal here.

## Where this comes from

This is the skeleton of the system I (Chi Zhang) run my life and company on, extracted. Every file was rewritten fresh from that private system for a stranger's first run: the structure, templates, and working loops ship; none of my data does. The private instance and this skeleton share a shape, and the shape is what you're looking at.

## What it is

Not an app. Markdown, folders, and small scripts that an agentic coding harness turns into an operating system. Claude Code is the first-class harness (the skills and hooks are Claude Code artifacts); anything that reads `AGENTS.md` can work the repo too.

What's inside:

- **A folder taxonomy with a contract.** Every folder has a stated purpose, lifecycle, and enforcer (`governance/repo-contract.md`). Your assistant always knows where a thing lives and when it dies or archives.
- **Governance as files.** How the assistant writes for you, what it may do freely vs. confirm first, what never leaves the repo, how builds run. The assistant reads these every session; you edit them like code.
- **Append-only records.** Decisions with their why, a one-row-per-session ledger, brainstorms, recurring reports. Your history stays greppable forever.
- **A wiki knowledge loop.** Paste a meeting transcript or a note; ingest lands it as a source page, distill extracts evidence onto entity and concept pages, triage promotes evidence into current truth with your yes. Runs entirely on the host agent: zero API keys.
- **Hooks and a hygiene checker** that keep the ledger written and the structure from rotting.

## Quickstart

```bash
git clone https://github.com/chizhangucb/nisse && cd nisse
python3 scripts/setup.py   # asks your name, personalizes the floor, checks the toolchain
claude                     # or your harness of choice
```

Then paste any meeting transcript or note and say "ingest this". Watch it land in `wiki/`, get distilled into linked pages, and queue for triage. That first loop is the magic moment; the rest of the system hangs off it.

## Tiers

Everything ships in the repo. Tiers are about dependencies, not importance.

- **Tier 1, works on clone, zero external accounts:** the taxonomy, governance, records streams, hooks, hygiene checker, and the wiki loop on pasted or local-file sources.
- **Tier 2, connectors, bring your own keys:** each one bolts onto a working tier-1 loop. Fireflies (meeting transcripts), Plaud (voice capture), AssemblyAI (re-transcription), Linear (ticket-tracker drift sweep). `.env.example` enumerates every variable; the Connectors section of `operations.md` is the human-readable list.
- **Tier 3, ships dormant:** the egress gate (approval-gated outbound actions, `scripts/egress_gate/README.md`), model routing (`scripts/litellm/README.md`), knowledge-graph config (`scripts/graphify/README.md`), and the phone-spoke pattern (`references/spoke-pattern.md`). Setup never touches these; each README is its own wiring-up guide.

## Layout

| Folder | What it holds |
|---|---|
| `context/` | who you are: business, priorities, goals |
| `records/` | 4 append-only streams: decisions, session ledger, brainstorms, reports |
| `plans/` | things written to build; `plans/workstate/` for live task state |
| `scripts/` | deterministic pipeline mechanics |
| `wiki/` | the knowledge layer: sources, entities, concepts, synthesis |
| `graphs/` | knowledge-graph registry (artifacts generated, gitignored) |
| `projects/` | one folder per workstream |
| `contacts/` | local contact store, one YAML per person |
| `references/` | lookup material you consult to do work |
| `governance/` | the rules; start with `governance/README.md` |
| `archives/` | retired material, mirror-pathed for easy restores |

`AIOS.md` at the root is the map the assistant loads every session (`CLAUDE.md`, `AGENTS.md`, and `GEMINI.md` are symlinks to it, so every harness reads the same floor). It points; it never restates.

## One rule to keep

This repo is designed to hold your real life: decisions, meetings, money, people. Treat the private instance you build from it as private infrastructure. `governance/confidentiality.md` is the template for what never leaves, and the wiki routes anything sensitive to `wiki/confidential/` by default. Fill those in before you feed the system anything real.

## Family

nisse is one of three local-first tools that work on their own and know about each other:

- **nisse** is the repo your assistant lives in: taxonomy, governance, records.
- **[Chronicle](https://github.com/chizhangucb/chronicle)** answers what happened in a session, in depth.
- **[Varde](https://github.com/chizhangucb/varde)** is an operator console over your whole AI stack: spend, permissions, and what needs your eyes today. It reads a nisse-shaped repo for the authority picture: egress policy, kill switch, decisions and the routing roster.

## License

Apache-2.0. See [LICENSE](LICENSE).
