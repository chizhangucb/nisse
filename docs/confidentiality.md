# Confidentiality

Some material never leaves this machine. Confidential material stays off email, Slack, X, public repos, published artifacts, and any person or service outside the owner, unless the owner says otherwise for that specific thing.

## What is confidential

Fill this in for your own life. The shape that works:

- Anything under a pending NDA.
- Unannounced money: revenue, fundraising, valuation, compensation.
- Named people who have not gone public: prospects, partners, candidates.
- Work whose existence is the secret, not just its contents.
- The wiki by default, and `wiki/confidential/` above all.

## The marker

A folder whose contents are confidential holds a file named `CONFIDENTIAL`. Sensitivity travels with the folder, so it never goes stale the way a path list does. Make a new folder confidential by dropping a `CONFIDENTIAL` file in it. This doc names the standard; it never lists paths.

## The guard

The pre-push secret scan (`scripts/guards/pre-push-secret-scan`, installed by `scripts/guards/install_push_guard.py`) on any repo with a public remote fails the push when a `CONFIDENTIAL` marker or a secret is in the pushed range. Keep your own instance of this kit on a private remote, so confidential trees back up there by design and the guard stops them from reaching anywhere public.

## When unsure

Ask the owner. Do not guess whether something is public.
