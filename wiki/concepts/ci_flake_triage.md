---
type: concept
tags: [ci_pipeline]
project: work
created: 2026-01-05
updated: 2026-01-05
sources: [2026-01-05_example_weekly_sync]
confidential:
---

> [!note] FAKE example concept page, shipped so you can see what distill produces against a common noun. Delete it after your first real distill, with the owner's yes.

# Current truth (last updated: 2026-01-05)

- **Method today:** a failure in the payments suite is classified by rerunning it three times. Nobody has costed the reruns [[2026-01-05_example_weekly_sync]].
- **What fixed the volume:** pinning the runner image, which halved the flake rate. It did not fix classification, which is the part that still costs a person.

## Open decisions

- Is rerun-three-times worth replacing with a real quarantine list, or is the payments suite the whole problem?

> [!question] Open: flake triage, is the payments suite a cause or a symptom?
> **One side:** the remaining failures cluster in payments, so fixing that suite ends the problem (Priya Patel) [[2026-01-05_example_weekly_sync]]
>
> **Other side:** clustering is what you would see if the triage method itself were unreliable, whatever the suite (inference)
>
> **The question:** fix the suite, or fix how a failure gets classified
>
> **Status:** open since 2026-01-05

# Evidence

- 2026-01-05 | Runner-image pinning halved the flake rate; the rest concentrate in the payments suite | #ci_pipeline | Source: [[2026-01-05_example_weekly_sync]] (primary)
- 2026-01-05 | A real failure cannot be told from a flake without three reruns | #ci_pipeline | Source: [[2026-01-05_example_weekly_sync]] (primary)
- 2026-01-05 | Rerun-based triage is an uncosted standing tax on the team | #ci_pipeline | Source: [[2026-01-05_example_weekly_sync]] (inference)
