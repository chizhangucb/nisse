# nisse

A starter kit for a personal AI operating system: one repo holding the owner's context, knowledge, and the standards agents follow when working for them. The owner clones it, fills in `context/`, and runs the wiki loop; nothing here governs any other repo.

## Language

**Starter kit**:
This repo as shipped: the frame a stranger clones and makes their own. The wiki loop is the product; the conventions are the frame around it.
_Avoid_: skeleton, abstraction repo, template, hub

**AIOS**:
An owner's personal instance of this kit, and the agent persona that works in it.
_Avoid_: hub, workspace

**Owner**:
The person whose repo this is. Sets standards, curates sources, gives every yes.
_Avoid_: user (ambiguous with the agent's user turn), Chi

**Upstream**:
The private instance nisse is extracted from by hand, on no schedule. Nisse lags it on purpose; nothing syncs them.
_Avoid_: source of truth, satellite, spoke

**Standard**:
A documented convention agents follow and code review checks against. Lives in docs.
_Avoid_: rule, guardrail, gate, floor, invariant, governance

**Guard**:
A hook or test that fails loudly when a standard is violated. Lives in code. A standard that can be a guard ships with one; an agreement only remembered is not shipped.
_Avoid_: gate, guardrail, tripwire, enforcer

**Skill**:
A judgment procedure an agent runs, defined by a SKILL.md.
_Avoid_: stub

**Script**:
Deterministic mechanics a skill or the owner calls directly. Survives only while something calls it.
_Avoid_: pipeline, helper, machinery

**Spec**:
What to build for one piece of work. Lives in a GitHub issue.
_Avoid_: plan, PRD, feature design, workstate

**ADR**:
A record of one hard-to-reverse decision. Lives in docs/adr.
_Avoid_: decisions log, decisions ledger, records

**Issue**:
A unit of tracked work on the GitHub issue tracker for this repo.
_Avoid_: ticket, Linear

**Wiki**:
The knowledge layer under wiki/, with its own binding schema (`wiki/AGENTS.md`).

**Tiers of truth**:
A live wiki page's three sections, from raw to settled: Evidence, then Current truth, then a synthesis page. The sections are the tier markers; each is written by a different operation.

**Evidence**:
The append-only ledger at the bottom of a live wiki page: dated, cited, trust-classed bullets. Written by distill, never rewritten.

**Current truth**:
The settled top section of a live wiki page, under 250 words. Rewritten only by triage, only with the owner's yes. Not the same as Evidence.

**Signals**:
The self-sufficient bullet list on a source page that distill reads instead of re-opening the raw capture.

**Distilled**:
The closing section of a source page: one line per page the source touched, or "(No durable updates.)". Also the frontmatter stamp marking a source as processed.

**Source**:
One wiki page per raw item (digest, takeaways, signals), living in wiki/sources. Distinct from the raw capture it mirrors.

**Source class**:
The trust mark on an Evidence bullet: (primary) the owner was in the room, (external) someone else's published claim, (inference) the agent's synthesis.

**Archive**:
Evidence rotated out of a living wiki page into wiki/archive, uncapped cold storage. Read only when the live page's pointer sends you there.
_Avoid_: annex, archives folder

**Confidential**:
Material that never leaves the owner's machine, marked by a CONFIDENTIAL file in its folder and named as a standard in docs/confidentiality.md.
