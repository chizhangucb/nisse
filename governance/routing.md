# Routing

> **Tier 3, ships dormant.** Nothing reads this file until you wire a model router. The wiring guide and LiteLLM example config live in `scripts/litellm/`. Until then, your harness's own model is the only lane and this file is just the policy you'll grow into.

Canonical routing policy for every spoke (any agent or job that selects or forwards a model call). Which model may touch a task is both a cost and a trust decision, so both live here. This file is the brain; the router config is the limb: it enforces what this file decides, it does not decide.

## Billing lanes: route by who already paid

A subscription is reachable only through its sanctioned CLI (OAuth), never as an API key a gateway can hold. Route each task to the lane that already covers it. Never extract subscription OAuth into a gateway (ToS violation).

- **Lane A. Your primary harness's work**, native, on its subscription. Marginal cost near zero. Bypasses the router.
- **Lane B. A second subscription CLI** (if you have one), driven natively. Bypasses the router.
- **Lane C. Everything else** (metered API models, local models). Through the router, metered. The only lane the router meters.

Lanes A and B bypass routers by design: a router forces metered API billing and throws away the subscription.

## Router spine

One instance, one config file, OpenAI-compatible endpoint on loopback only. Config-file authoritative (no database overlay). Every metered spoke points at this one endpoint. Gate the endpoint with a master key (env ref, never inlined; value in the canonical store per `secrets.md`). Before any cloud, multi-tenant, or network-exposed deploy, add network controls and rotate the key.

## Confidentiality posture: minimal gate

Decide your threat model explicitly. A sane default:

- Reputable no-train destinations are allowed for all content tiers.
- The one hard block, at any tier, is train-on-your-data and free-tier aggregator destinations, because training leakage can regurgitate your content into other people's outputs.
- A stricter per-tier gate (pinning your most sensitive content off all hosted proxies onto direct-provider or local only) is a deliberate future tightening; write down the trigger that would make you flip it.
- Enforce no-train in router config (e.g. OpenRouter `provider.data_collection: deny` per deployment), not with tag filtering; a tag a spoke can omit is not a security boundary.

## Roster

Hand-curated and committed, split by volatility: judgments (tier, trust, task-fit) never auto-change; volatile facts (price, context window) auto-refresh from public catalogs. Hard rule: a new model never enters routing until you deliberately add it with a tier and a trust level.

| Model | Route | Tier | Trust | Task-fit | Lane | Price in/out | Context |
|---|---|---|---|---|---|---|---|
| (add models here) | | | | | | | |

## Escalation (does this task deserve a frontier-tier call)

- Triggers: **Taste, Architecture, Strategy, Review, Codify.** Hit none and it is not a frontier task. Codify means turn the judgment into a reusable rule so you pay for it once.
- Hard cost gate: never fire a frontier-tier call without showing the trigger, estimated tokens, and dollar cost. A configurable auto-approve-under ceiling keeps it from being nagware.
- Compression mandate: a frontier tier gets a short briefing, never raw sources.
