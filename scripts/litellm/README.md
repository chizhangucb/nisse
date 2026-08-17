# Model-routing spine (tier 3, ships dormant)

An example LiteLLM config implementing `governance/routing.md` (the brain; this is the limb). Nothing runs until you wire it; setup never touches this folder.

## Wiring up

1. `pip install 'litellm[proxy]'` (or run it in a venv).
2. Copy `config.example.yaml` to `config.yaml` and edit the roster: one entry per model you deliberately admit, per the routing.md hard rule (a model never enters routing until you add it with a tier and trust level).
3. Put `OPENROUTER_API_KEY` and `LITELLM_MASTER_KEY` in your canonical secrets store (`governance/secrets.md`); never inline them in the yaml.
4. Run loopback-only: `litellm --config config.yaml --host 127.0.0.1 --port 4000`.
5. Point your metered spokes (anything that is not a subscription CLI) at `http://127.0.0.1:4000` with the master key.

## The two rules the example encodes

- **No-train enforcement in config, not tags:** every OpenRouter deployment carries `provider.data_collection: deny`, so a spoke cannot reach a train-on-your-data host by omitting a tag. Best-effort (the upstream's data tags are their claim, not a guarantee), but it is the right layer.
- **Config-file authoritative:** no database overlay, so this file is the whole truth and diffs in git.

Cloud caveat: master key + loopback is laptop-grade auth. Before any network-exposed deploy, add real network controls and rotate the key.
