# Skill Authoring

How skills get built and written in this repo. Applies to skills and to editing any governance file. Constraints and gates only; general craft guides (your harness's skill-writing docs) win wherever this file is silent.

## Process

- Plan-first and review-first bind here: see `building.md` (general build discipline, applies to any skill or governance edit).
- Skill evals, benchmarks, and headless batch runs never run from a real project directory (each headless session writes a transcript into that directory's projects folder and buries your real sessions). Use a throwaway cwd like `/tmp/skill-evals`, or skip evals for personal skills.

## Format

- Default: one SKILL.md per skill, frontmatter exactly two keys (name, description). Single file until the content outgrows it.
- Scale up to a fuller scaffold when the content earns it: `scripts/` when every run would rewrite the same deterministic helper; `references/` for lookup material too big for the body (~300+ lines); `assets/` for templates used in output.
- The scaffold choice is a design call: name it in the plan doc with a one-line why.
- Description pattern: what it does, then "Use whenever the owner says..." with concrete trigger phrasings, then a "Not for X (other-skill)" tail.
- No markdown `#` marks or unquoted YAML-special characters in the description: an unquoted `#` starts a YAML comment and silently truncates it.
- Layout: tables for enumerable rules, terse numbered prose for judgment steps, and exactly one boundary surface: an Is/is-not table where sibling-skill handoffs matter, else a "Do not" list.

## Length and sediment

Applies to every operating doc: skills, rules files, `wiki/CLAUDE.md`, `wiki/rules.md`.

- Word budget: every SKILL.md stays under ~500 words (`wc -w`, frontmatter included). Over budget means move content out (templates, scripts, references, a shared rules file) or delete it, not tolerate it. The hygiene checker flags violations.
- Lessons enter as rules, never as stories. A new rule enters an operating doc as the imperative only, plus at most a one-clause pointer to `records/decisions.md`; the story (incident, alternatives, dates) goes to the log in the same session. Test each sentence: if deleting it would not change behavior on the next run, delete it whole.
- Never restate a file the skill already says to read. One binding source; the skill points, it does not mirror.

## Review by blast radius

Review scales with what a skill can do.

| Skill | Gate |
|---|---|
| Touches confidential paths, external send, git push, spend, or broad hub mutation; or imported from outside | The owner reads and audits it themselves (imported always vetted) |
| Low-risk, self-authored (read-only, local, formatting) | Self-evolves behind the periodic diff review |

Writing quality holds for all: plain words a first-time reader gets, no idiom shorthand, no bare syntax without a gloss; steering phrases survive verbatim even when trimming; reread as a stranger before done.
