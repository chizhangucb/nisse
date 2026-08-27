# governance/

The rules your assistant obeys, as files you edit. The assistant loads the map (`AIOS.md`) every session and pulls these in on demand; changing a rule here changes behavior everywhere, immediately. Treat them like code: version them, review diffs, keep them short.

## Templates, not scripture

Every file here is a template with two kinds of content:

- **Structure (keep):** the section shapes, the gating levels, the append-only rules, the fail-closed defaults. These carry the operating experience the skeleton was extracted from; gut them and the loops downstream stop making sense.
- **Specifics (yours):** every concrete preference, category, cap, audience, and example. They ship as working defaults or placeholders so you can see the shape filled in, and they're written to be replaced. If a rule doesn't apply to your life (no investors, no team, no social media), delete it; a rule you don't mean is worse than no rule, because the assistant will hold you to it.

The two most personal files, customize before feeding the system anything real:

- `communication-style.md`: how the assistant writes for you. Ships with one person's defaults as examples.
- `confidentiality.md`: what never leaves without your explicit yes. Ships with placeholder categories.

## Reading order

1. `repo-contract.md`: the layout contract; what every folder is for.
2. `communication-style.md` + `confidentiality.md`: personalize.
3. `tool-actions.md` then `gating.md`: what's auto vs confirm-first, and the model behind it.
4. `building.md`, `skill-authoring.md`, `secrets.md`: build discipline, skill craft, credential storage.
5. `ticket-tracker.md`, `satellite-repos.md`, `routing.md`: dormant until you wire a tracker, a second repo, or a model router.
