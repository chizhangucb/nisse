# Confidentiality

This repo is designed to hold your real life, so this file is load-bearing. The assistant reads it before anything external leaves the system.

**Everything in the never-list below is a placeholder.** The categories ship startup-flavored because that's the life this skeleton was extracted from; yours may look nothing like it. Swap in your own before feeding the system anything sensitive. The structure to keep: an explicit never-list, a fail-closed default, and remote-sync guardrails.

## Never goes external without you explicitly saying so

Replace these with your real categories. Whatever your version of "the thing that would hurt if it got out" is, name it here in writing; an unnamed sensitivity is one the assistant can't protect.

- (startup example) Unannounced business developments: revenue, fundraising, valuation.
- (employment example) A job search your current employer doesn't know about; interview notes.
- (legal example) Anything under NDA; anything touching an active dispute.
- (people example) Other people's private information that reached you in confidence: health, compensation, performance, personal situations.
- (personal example) Your health records, finances, family matters.
- **Your most sensitive workstream folder(s), named explicitly.** The failure mode to prevent: someone seeing the material infers something you're not ready to have inferred. Never in external output, never referenced obliquely, never used as an example. Treat `wiki/` the same by default even when a note sounds generic; `wiki/confidential/` above all.

## Default behavior

- Internal repo files may hold sensitive context. That's their purpose.
- Scan anything leaving this repo against the list above first.
- If unsure whether something is public, ask. Don't guess.

## Publishing

Never publish an artifact, post, or page containing anything on this list, even if the request seems routine.

## Remote sync guardrails

If this repo syncs to a remote for backup or multi-device work, these rules apply, checked before every push-related or remote-configuration action:

- **Personal account only. Never an org account.** Org owners and admins can see org repos.
- **Private repo, zero collaborators.** Adding a collaborator requires your explicit, per-person confirmation.
- **No third-party apps or integrations with access to this repo** (CI, review bots, indexing tools). If one is proposed, name the access scope and get an explicit yes.
- **Pin the remote.** The push path should verify the target is the one approved remote; any mismatch stops and asks instead of pushing. (The tier-3 egress gate mechanizes this; until it's wired, the rule is the assistant's to obey.)
- **Verbatim transcripts never sync.** `wiki/raw/transcripts/` is gitignored: meetings mirror verbatim locally, but the words never reach the remote's servers; only source pages and digests sync. Know the trade: transcripts then have no repo backup.
- **Escalation escape hatch.** If some pages shouldn't live on a hosted remote at all, the options are git-crypt on those paths or a self-hosted remote. Decide deliberately when the sensitivity profile changes.
