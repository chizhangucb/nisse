# Secrets: where credentials live

Binding rule for API keys and credentials. Stops file-choice drift.

## The one rule

One canonical store per secret. Every other place references or is propagated from it. Never hand-copy a value between files.

## Where each kind goes

- **Account-wide key** (one key per service, reused across tools: transcription, tracker, model gateways): canonical file `~/.secrets/shared.env`. `chmod 600`, dir `chmod 700`, outside every git repo. At rest: full-disk encryption (verify it's on).
- **App-specific secret** (scoped to one app: a project's `DATABASE_URL`, a bot token): stays in that app's own `.env`. Don't centralize; it buys nothing and widens blast radius.
- **Harness-only key** your agent harness must read directly from its own config: a named exception, documented here per instance. Intentional copies, not drift.
- This repo's `.env` (gitignored) is a last-resort fallback for connector keys; `.env.example` (tracked) enumerates every variable the connectors understand.

## How consumers get the shared keys

Canonical is the single edit point. Consumers reach it three ways.

- **Repo scripts**: read canonical directly. Loaders resolve env var first, then `~/.secrets/shared.env`, then repo `.env` as last resort. No copies.
- **Shell consumers**: `set -a; source ~/.secrets/shared.env; set +a`. No copy.
- **A consumer that can only read its own env file** (some daemons regenerate their launch config and wipe injected env): its file is a DERIVED copy, pushed by a propagation script that overwrites only keys the target already declares, so per-app scoping holds. The one place a shared value is copied; never hand-edited.

## Rotating a shared key

1. Edit the value in `~/.secrets/shared.env`.
2. Re-run your propagation script if any derived copies exist.
3. Everything else picks it up next run; restart long-lived daemons to reload.

## Why not a keychain or password manager by default

Autonomous consumers read literal files under a scheduler, no shell profile. An OS keychain needs a fetch shim per launch point and a fragile headless ACL; its edge (encryption at rest) is already full-disk encryption's. A hosted manager in headless mode still needs a plaintext service-account token, trading N keys for 1 token plus a dependency.

## Upgrade path (when triggers hit)

Do not upgrade speculatively. Move off the plaintext file when any becomes true: secrets sync to a second machine or into git; another person needs a subset; automatic rotation or an audit trail is required; one leaked file would be catastrophic.

- **Tier 2 (single machine, next step): sops/age with a hardware-backed key** (on a Mac, `age-plugin-se` with the Secure Enclave). Encrypted files safe on disk, in git, or synced. Create the key without user-presence so scheduled jobs decrypt unattended.
- **Tier 3 (multi-machine / cloud / team): workload identity + a secrets manager.** The process proves identity (OIDC/IAM), gets short-lived auto-rotating creds, stores no long-lived secret.
