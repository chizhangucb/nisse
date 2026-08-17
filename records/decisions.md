# Decisions

Append-only record of decisions and why. Newest block at the TOP.

**Logging bar, log iff:** (1) changes future behavior (policy/structure/schema/rule), (2) commits something hard to undo, or (3) settles a question a future session would re-litigate. Never logged: task completions, preferences already in rules, one-off no-recurrence choices.

**Format:** one `## YYYY-MM-DD: Title` header (append `(session <id>, stream: <name>)`; hooks and pipelines parse these, so never alter them), then one bullet per decision: `- **Decision stated.** Why clause. → pointer`. Bold lead is the decision, then a short why, then a pointer to the source with the long story (brainstorm Q#, plan doc, file path). Aim ~30 words per line; push detail to the pointer, never truncate meaning. A block with multiple decisions gets multiple bullets. Written in-flow by the deciding session, never deferred.

---

<!-- log-shards -->
Rotated history:
(none yet; rotated months land in decisions_history/)
<!-- /log-shards -->
