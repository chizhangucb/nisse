# graphs/

Knowledge-graph registry and artifacts. `index.json` (committed) is the registry of every graph: name, source path, output dir, build mode. Artifacts live under `graphs/<name>/graphify-out/` and are gitignored: generated, rebuilt on schedule, never hand-edited.

Dormant until wired (tier 3): the wiring guide is `scripts/graphify/README.md`. Two kinds worth knowing about: code graphs (structural extraction, no LLM, no network) and docs graphs (semantic, model-extracted, so the one kind that routes content and needs a confidentiality gate on its corpus).
