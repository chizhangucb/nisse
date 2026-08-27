# Design rubric

UI and design rules for every interface you build. On-demand: load before building or reshaping any UI. Ships as a worked example from one real calibration pass; replace the specifics with your own the first time you run this gate for real.

## Type scale

- Body text at or above your accessibility floor (commonly 16px). Pick a default and let yourself tune a point or two either way.
- Build the scale as tokens (a single source), so a global resize is a one-line change. Never hardcode sizes per component.
- Chrome never larger than content. Chips, pills, toggles, legends, kbd hints sit at the smallest label tier.

## Contrast

- Contrast discipline beats size. A contrast fix can rescue a size you'd previously rejected as too small.
- On dark surfaces: primary content ~15:1+ (near-white), secondary ~8:1+, nothing below 4.5:1 on words that must be read.

## Three-tier ink (the structural rule)

- Content renders in the primary ink.
- Muted tier is labels and metadata only, never sentences.
- Faint tier is chrome only (arrows, dividers, kbd hints), never readable words.
- Classic failure mode: most of a page silently rendering in muted or faint. Guard against it.

## Small type

- Sub-15px type (dense, Linear-style UI) survives only with all three of: extreme contrast discipline, tight line lengths, generous whitespace. Missing any leg, go bigger.

## Acceptance bar

- Zero strain at 100% browser zoom on every display you actually use. Calibrate empirically with a live size/contrast switcher when in doubt, not by convention.
- Named comfort references worth anchoring to: a code editor's markdown preview (~19px, ~10:1), a dense app's gray-hierarchy labeling for secondary text, a high-contrast near-white-on-dark terminal.

## Provenance

Born from a real readability gate run against a live UI pass, where contrast discipline turned out to matter more than size. Log your own gate's outcome in `records/decisions.jsonl` and the plan doc that drove it, then fold anything durable back into this file.
