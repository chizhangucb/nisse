# Gating

The one model for whether an action auto-proceeds, needs one tap, needs review every time, or is hard-blocked. Human intent is the source of truth; the machine layers reconcile to it. `tool-actions.md` is this file's operational view; on conflict, this file wins.

## The model

- Four outcome levels:
  1. **Auto.** Proceeds, no interaction.
  2. **Card.** One interaction (an inline prompt, or an out-of-band ping if you wire one). A standing grant you gave can pre-satisfy it.
  3. **Review-every-time.** A card every time, forever. No grant retires it.
  4. **Hard-block.** The acting agent may never be the approver; needs a different principal. A confidentiality hit is its content-side sibling: blocked regardless of who asks.
- Two axes only: **action class** x **approver-reachable-right-now** (at the keyboard / away but pingable / fully unattended).
- **Driver is audit-only.** Who initiated (you, an autonomous agent, another harness) is logged, never lowers approval. No forgeable marker grants your authority.
- **One owning layer per action class**, not a multi-way vote. Each row names its single enforcer.

## The layers

- **Harness** (permission settings + hooks): local filesystem and edit surfaces. Out of the box this is the only enforcer; unattended actions it gates should deny, since nobody can approve.
- **Egress gate** (tier 3, dormant until wired): everything external, publishable, or spend. Once wired it holds the content scan and the out-of-band approval, the only layer that can approve while you're away from the keyboard. Its raw counterparts (raw `git push`, raw post commands) should then be denied at the harness so the gated path is the only path.
- **Server-side protection** (e.g. GitHub branch protection): the irreducibles a client can't enforce, like author != reviewer on merges.

## The table

Adjust postures to taste; keep every action class owned by exactly one layer.

| # | action | reachable | unattended | owner |
|---|---|---|---|---|
| 1 | reads, everywhere | auto | auto | harness |
| 2 | git commit | auto | auto | harness |
| 3 | delete: ephemeral (/tmp, build artifacts, gitignored) | auto | auto | harness |
| 4 | delete: tracked/repo paths | card | deny | harness |
| 5 | skills/ edits | auto + periodic diff review | auto | harness |
| 6 | governance/ edits (the .md rule docs) | auto when an approved plan covers the change | deny | harness |
| 6b | enforcement-machinery edits (permission settings, hooks) | explicit approval every time | deny | harness |
| 7 | wiki/records/plans/context edits | auto | auto | harness |
| 8 | git push | card (conditioned-auto once the egress gate + pinned remote + scan are wired) | deny (card via gate if wired) | harness or gate |
| 9 | PR merge | auto on green CI; red = card | same | server-side + harness |
| 10 | self-approve / claim-reviewed / own-work-to-Done | hard-block | hard-block | server-side + harness |
| 11 | chat/email/social sends | card | deny (card via gate if wired) | harness or gate |
| 12 | publish anything public | card every time, never auto | same | harness or gate |
| 13 | spend | auto under your caps (`operations.md`); over = card | same | harness or gate |
| 14 | unclassified catch-all | card + classify | deny | harness or gate |

## Immovable floors (no posture relaxes these)

- A confidentiality hit hard-blocks, content-side, regardless of principal.
- Unclassified actions fail closed (card when reachable, deny when not).
- No allow-rule may ever cover a self-approval shape (approving your own PR, moving your own work to Done).
- PUBLISH never auto-approves.
- No approval card auto-proceeds on silence. Expired cards queue for later. Default-if-silent is a decision-queue tool only, never a gate.
