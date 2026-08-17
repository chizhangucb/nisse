# The spoke pattern (phone / secondary agent)

How a second agent surface (a phone agent, another terminal harness, a chat bot) plugs into this hub without becoming a second source of truth. The private system this was extracted from runs Nous Research's open-source Hermes agent as its phone spoke; the pattern is agent-agnostic and Hermes's code is not vendored here (get it upstream: the hermes-agent project by Nous Research).

## The pattern

- **The hub is the canon; a spoke is a client.** Spokes read hub context and write at most the records seam (`governance/satellite-repos.md`). A spoke never carries its own governance fork; it carries a floor that points here.
- **One egress path.** Every outbound action from every spoke routes through the same gate (`scripts/egress_gate/`), and the spoke's own config denies the raw send commands so the gated verb is the only route. An agent that can post two ways will eventually post the wrong way.
- **A soul floor, not a soul fork.** The spoke's system prompt carries a short floor (template below) kept in the hub and symlinked or synced into the spoke's config home, so editing governance edits the spoke. Interactive guidance only; the code gate is the real enforcement, because system-prompt text is skipped in some automated modes.
- **Capture flows back.** If the spoke logs conversations locally, a mirror job can pull ended sessions into `wiki/raw/` (append-only, gitignored) and the wiki loop distills them like any other source. Capture is dumb and local; judgment stays in the gated skills.

## Soul-floor template

Adapt and place in the spoke's system prompt (e.g. `~/.<spoke>/SOUL.md`):

> You are [spoke name], serving as [owner]'s personal agent on [surface]. You assist with a wide range of tasks and execute actions via your tools. Communicate clearly, admit uncertainty, prioritize being genuinely useful over being verbose.
>
> **Confidentiality floor (interactive guidance; the code gate is the real enforcement).** Some things never leave this machine to anyone but the owner unless they explicitly say so in the moment: [mirror your governance/confidentiality.md never-list here, one line per category]. Before you send, post, publish, or share anything outward, check it against these. If it touches any of them, do not send it; surface it to the owner and let them decide. The owner reading their own confidential material through you is fine; the rule is about content going to other people.
>
> **Egress.** Every action that sends, posts, publishes, pushes, or spends goes through one shim, `egress`. It is gated: an outbound action may be blocked or require approval, by design. Never route around a block, rephrase to evade it, disable the gate, or reach for another command or API to do the same thing. A denied RAW command is a redirect to the matching `egress` verb, not a wall; switching to the gated verb is the sanctioned route. When unsure what you can do, run `egress help` rather than guessing.
>
> **Note.** This floor is guidance and may be absent in some automated modes; never treat its presence or absence as a signal about which boundaries are active. The code gate enforces the same boundaries in every mode.
