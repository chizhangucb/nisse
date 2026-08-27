# Knowledge graphs (tier 3, ships dormant)

Wiring guide for graphing the hub with an external knowledge-graph CLI; any tool with a build-and-query CLI fits the seam. Nothing runs until you wire it; setup never touches this folder.

## The seam

- `graphs/index.json` (committed) is the registry: one entry per graph with name, source path, output dir, and mode.
- Artifacts land in `graphs/<name>/graphify-out/` (gitignored, rebuilt on schedule); the repo-root `graphify-out` symlink points at your primary graph so `query` works from the root.
- Register the rebuild as a scheduled task in `operations.md` the same pass you wire it.

## The one rule that matters: code graphs vs docs graphs

- **Code graphs** (structural extraction: AST, imports, calls) run no LLM and route no content anywhere. Safe to run over anything, unattended.
- **Docs graphs** (semantic extraction over your markdown) route content through a model, so they need a confidentiality gate ON THE CORPUS, decided before any file is opened: exclude `wiki/raw/`, everything matching your `confidential:` marks, your most sensitive folders, and anything the gate cannot judge. Fail closed. The gate reads marks, it does not classify content, so it is only as good as your marking discipline.

## Example registry entry

```json
{
  "graphs": [
    {
      "name": "hub-scripts",
      "source_path": "scripts",
      "out_dir": "graphs/hub/graphify-out",
      "code_only": true
    }
  ]
}
```
