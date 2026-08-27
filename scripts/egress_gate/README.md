# Egress gate (tier 3, ships dormant)

One shim between your agents and the outside world. Every action that sends, posts, publishes, pushes, or spends routes through `egress <verb> ...`; the gate classifies it, scans it against your confidentiality markers, and either proceeds, asks you, or blocks. Posture model: `governance/gating.md`. Nothing here runs until you wire it; setup never touches this folder.

## What the code layer does

- **Classify:** every verb has a row in `data/classification.json` (class: read / send / publish / spend; posture: auto / ask / confirm-always / conditioned-auto). An unclassified command fails closed: ask when you're at the keyboard, deny when not.
- **Scan:** command text (and for `git push`, the full outgoing diff) is scanned against `data/confidential_markers.json`. A hit hard-blocks, regardless of who asked or what the posture says. That's the content-side floor from gating.md.
- **Pin:** `git push` verifies the remote matches the per-repo pin in the classification file. Clean scan + pinned remote + expected branch = auto (if posture is conditioned-auto); any trip asks instead.
- **Fail visible:** a send that does not fire always prints why and the fix. Never a silent no-op.
- **No who-initiated input:** the gate reads the command, the content, and the config. No env var or session marker lowers approval; that keeps a confused or compromised agent from granting itself your authority.

## Wiring up

1. Copy the two example files and make them yours:
   - `data/classification.example.json` → `data/classification.json` (verbs, postures, your repo pins)
   - `data/confidential_markers.example.json` → `data/confidential_markers.json` (the regex/phrase list distilled from your `governance/confidentiality.md` never-list)
2. Put the shim on PATH: `ln -s "$(pwd)/scripts/egress_gate/egress.py" /usr/local/bin/egress` (or an alias).
3. Deny the raw forms in your harness so the gated path is the only path: add harness permission rules denying raw `git push` and your raw post/send commands. Routing through the gate only means something if the raw form is closed.
4. Test: `egress git push --dry-run` and one deliberate marker hit; confirm the block prints the reason.

## What deliberately does NOT ship

Instance-layer machinery: anything that depends on your channels and tokens. An instance can grow out-of-band approval (a phone ping that releases exactly one approved command), per-channel send verbs with attribution footers, or standing grants you've tapped; all of that slots into the ask path here (`confirm()` is the seam), and none of it can ship generically because it is made of your accounts.
