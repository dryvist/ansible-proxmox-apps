# llm_router

Deploys a [LiteLLM](https://github.com/BerriAI/litellm) proxy — the LLM fabric's
single OpenAI-compatible front door — on each guest tagged `llm-router`. Native
install: a Python venv + systemd, config at `/etc/litellm/config.yaml`. Fronted by
Traefik at `https://llm.<subdomain>`; consumers select a tier purely by model alias,
so the backend topology is swappable with no app change.

## Installation

Ships with the `ansible-proxmox-apps` repo; no external install. Wired into
`playbooks/site.yml` against `llm_router_group` (guests tagged `llm-router` in the
tofu inventory). Tools come from the repo's Nix dev shell (`direnv allow`).

## Tiers (one proxy, two backends)

| Alias(es) | Backend | Auth |
| --- | --- | --- |
| `gpt-oss-120b`, `Qwen3-Coder-30B-A3B`, `Qwen3.6-35B-A3B-4bit`, `claude-sonnet-5` | `llm-large` runner (`/v1`, bearer) | `LLM_LARGE_BEARER_TOKEN` |
| `qwen3-4b`, `embeddings`, `claude-haiku-4-5` | `llm-fast` (GPU) **and** `llm-light` (CPU) | none |
| `openrouter-free` (extensible list) | OpenRouter (paid-SaaS egress) | one key **per model** |

Each light alias is registered as **two deployments** with the same `model_name`
(the GPU `llm-fast` box and the CPU `llm-light` standby). LiteLLM load-balances the
pair and cools a failed deployment down (`allowed_fails` / `cooldown_time`), so a GPU
outage drains to CPU automatically. There is **no** cross-tier fallback — a large
request that fails surfaces the error rather than silently degrading to a small model.

## OpenRouter egress tier (optional, per-model keys)

`llm_router_openrouter_models` registers explicitly-named aliases for
OpenRouter-hosted models. Deliberate properties:

- **One OpenRouter API key per MODEL** (never per harness/caller). Each entry's
  `key_field` names its field in the OpenBao paid-SaaS key area
  `secret/ai/saas/openrouter`; the `openbao_secrets` pre-play delivers it via
  the `ai-saas-openrouter` policy leaf, and the rendered EnvironmentFile
  carries it as `OPENROUTER_API_KEY_<KEY_FIELD upper-snaked>`.
- **Inert until seeded** — an entry whose key is absent renders nothing, so
  the list is safe to extend before the key exists.
- **Opt-in only** — OpenRouter aliases are never chained into `ai-default`
  rotation or fallbacks; consumers (Hermes, Open WebUI, workstation harnesses)
  must name the alias to reach the SaaS egress.

Seeding a new model (operator, once per model): mint a scoped key in the
OpenRouter console, then
`bao kv patch secret/ai/saas/openrouter <model-slug>=<key>` and re-converge
this role. The first entry is `openrouter-free` →
`nvidia/nemotron-3-ultra-550b-a55b:free` (rate-limited; NVIDIA logs prompts on
the `:free` endpoint — never send confidential material through it).

## Daily brain rotation (optional)

When `ai_rotation_enabled` (in `group_vars/all.yml`) is `true`, the router exposes
one stable alias, `ai-default`, that Hermes and Open WebUI point at permanently,
and two systemd timers flip which backend it maps to on a UTC schedule: **00:00 →
the large brain, 12:00 → the optimized brain** (`ai_default_model_large` /
`ai_default_model_optimized`, both first-class aliases in `llm_router_large_models`).
The flip is a `config.yaml` symlink swap between two pre-rendered per-phase configs
plus a `litellm` restart — no gateway restart, no Hermes cron churn. A
`ConditionPathExists` sentinel (`rotation-paused`) lets a bench window keep the
fabric on the optimized brain. Off by default: `config.yaml` is a single static
file and the render is byte-identical. Full rationale, capacity math, and the
flagship upgrade path: [`docs/BRAIN_ROTATION.md`](../../docs/BRAIN_ROTATION.md).

## Observability

`litellm_settings.callbacks: ["otel"]`:

- **OTLP/HTTP** traces to the Cribl Edge collector
  (`http://cribl-edge.<subdomain>:<otel_traces_http>/v1/traces`).

`/health/liveliness` is unauthenticated by design (LiteLLM load-balancer probe), so
Traefik health checks need no credential.

## Key variables (`defaults/main.yml`)

| Var | Default | Purpose |
| --- | --- | --- |
| `llm_router_api_port` | `service_ports.llm_router_api` | proxy listen port (no hardcode) |
| `llm_router_light_port` | `service_ports.llm_fast_api` | llm-fast / llm-light backend port |
| `llm_router_large_port` | `service_ports.ollama_api` | llm-large backend port |
| `llm_router_routing_strategy` | `simple-shuffle` | load-balancing across same-name deployments |
| `llm_router_master_key` | `env LLM_ROUTER_MASTER_KEY` (mandatory) | proxy master key |
| `llm_router_llm_large_bearer` | `env LLM_LARGE_BEARER_TOKEN` (mandatory) | llm-large bearer |

## Dependencies

- `terraform-proxmox` constants must expose `service_ports.llm_router_api` **and**
  `service_ports.llm_fast_api` (added by the parallel constants PR). Both are
  hard-required — a missing constant fails loud.
- Secrets `LLM_ROUTER_MASTER_KEY` + `LLM_LARGE_BEARER_TOKEN` are env-sourced
  (SOPS/Doppler) today; the OpenBao migration is a separate phase.
- `prisma` is installed into the venv even though the proxy is DB-less:
  litellm[proxy] no longer pulls it, and LiteLLM's auth-error handler
  unconditionally imports it to classify DB outages — without it, a rejected or
  absent API key raised `ModuleNotFoundError` and returned 500 instead of 401.

## Usage

```bash
env -u DOPPLER_PROJECT -u DOPPLER_CONFIG -u DOPPLER_ENVIRONMENT doppler run -- \
  ./scripts/run-ansible.sh playbooks/site.yml --limit llm_router_group --tags llm_router,ai
```

## Not yet live-validated

Verify on the first converge: (a) `litellm[proxy]` + the `langfuse` / `otel`
callbacks import cleanly in the venv; (b) the `llm-large` runner accepts the bearer
on `/v1`; (c) the same-name GPU/CPU deployment pair drains as intended when the GPU
box is stopped.
