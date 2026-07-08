# Daily brain rotation

A built-in daily A/B for the LLM fabric: the fabric-wide default model rotates
between a **large** brain and an **optimized** brain on a fixed UTC schedule, so
the Hermes agent and the Open WebUI chat box always run the same default and that
default alternates twice a day.

- **00:00 UTC** → the **large** model.
- **12:00 UTC** → the **optimized** model.

The whole feature is behind `ai_rotation_enabled` (default `false`). With it off,
every rendered artifact is byte-identical to a non-rotating converge — this repo
can carry the mechanism without changing live behaviour until the switch is
flipped.

## Chosen actuator: a stable router alias whose backend rotates

Consumers (Hermes, Open WebUI) point at one **stable** router alias, `ai-default`,
forever. Only the LiteLLM router's mapping of `ai-default` → concrete backend
flips at 00:00/12:00. Nothing else in the fabric moves.

```text
Hermes  ─┐
         ├─ model id "ai-default" ──▶  LiteLLM router  ──▶  { large | optimized }
OpenWebUI┘        (never changes)         (mapping flips 2×/day)
```

### Why this shape, and why not the others

Four actuators were evaluated. The alias rotation is the only one that is
**CI-credential-free, idempotent under Ansible, and free of a gateway restart and
cron-snapshot churn** at the same time.

1. **Scheduled GitHub Actions workflow** that converges with
   `-e ai_default_model=…` — **discarded.** Ansible converge is interactive-only
   in this repo (see `AGENTS.md` → "Development workflow"); the self-hosted
   runners run read-only E2E *tests*, not credentialed converge. Standing up
   converge-in-CI would mean plumbing OpenBao AppRoles, SSH keys, and Doppler
   into GHA — a large new secret surface for a twice-daily toggle.
2. **systemd timer on a guest that re-renders its own Ansible-managed config**
   and restarts the gateway — **discarded.** A guest mutating an Ansible-owned
   file out-of-band fights idempotency (the next converge reverts it) and still
   restarts the gateway (SIGTERM mid-chat) twice daily.
3. **Router-level alias rotation** (this design) — **chosen.** The twice-daily
   mutation is a single local symlink the router role manages as a
   deterministic, converge-safe value and the timers own between converges.
   Consumer configs stay static, so no gateway restart and no cron churn.
4. **Terrakube scheduled run / other existing timers** — none applies; no
   scheduled-converge primitive exists here.

### What the alias buys us (the three things a concrete-id rotation breaks)

Rotating the **concrete** model id everywhere (the naïve approach) forces a
twice-daily converge, because:

1. **Open WebUI** — `DEFAULT_MODELS` is set from env with
   `ENABLE_PERSISTENT_CONFIG=false`, so it is authoritative only at **container
   start**. Changing the concrete id means restarting the Open WebUI container
   twice a day.
2. **Hermes cron jobs** — unpinned jobs snapshot `model.default` at creation and
   **fail closed** on drift (upstream spend guard); they only re-seed on a
   converge (`roles/hermes_agent/tasks/main.yml`). A concrete-id change without a
   converge would silently stop the seeded cron fleet until the next converge.
3. **Hermes gateway** — a converge re-renders `config.yaml`/`.env` and restarts
   `hermes-gateway` (SIGTERM), killing any in-flight agent turn.

Pointing both consumers at the stable `ai-default` alias makes all three
non-issues: `model.default` stays `ai-default` (cron snapshots never drift),
`DEFAULT_MODELS` stays `ai-default` (no Open WebUI restart), and the gateway is
never touched by a rotation. The only process that restarts is `litellm` on the
router guests — a fast uvicorn bounce, acceptable as a scheduled 00:00/12:00 blip.

## Single source of truth for the model pair

`inventory/group_vars/all.yml` (one place, no scattered duplicates):

```yaml
ai_rotation_enabled: false                              # master switch
ai_default_model_optimized: Qwen3.6-35B-A3B-OptiQ-4bit  # 12:00 UTC brain
ai_default_model_large: gpt-oss-120b                    # 00:00 UTC brain (interim; see capacity)
# Derived pointer every consumer already reads. When rotation is off it equals
# the optimized id (byte-identical to the old literal); when on it is the alias.
ai_default_model: "{{ 'ai-default' if ai_rotation_enabled | bool else ai_default_model_optimized }}"
```

Both phase ids **must** be first-class aliases in
`roles/llm_router/defaults/main.yml:llm_router_large_models` — the router resolves
each phase's backend **and** its `context_window` from that existing table, so the
rotating `ai-default` alias always carries an explicit `max_input_tokens` (a null
there is the compress-to-death trap). No context values are duplicated for the
rotation; a phase id not in the table fails the converge loud.

## Mechanism (router role, `ai_rotation_enabled: true` only)

1. Render **two** complete configs from the one `config.yaml.j2`, differing only
   in the `ai-default` entry's backend/context: `config-large.yaml`,
   `config-optimized.yaml`.
2. `config.yaml` becomes a **symlink** to the phase that matches the current UTC
   hour (computed on the guest via `date -u`), so a converge always lands on the
   correct live phase and never clobbers it to the wrong one.
3. Two declarative systemd timers (`litellm-rotate-large.timer` at `00:00 UTC`,
   `litellm-rotate-optimized.timer` at `12:00 UTC`) each start a oneshot that does
   exactly `ln -sfn config-<phase>.yaml config.yaml` + `systemctl restart litellm`.
   No wrapper script, no time math — the schedule lives in `OnCalendar`.

With `ai_rotation_enabled: false` none of this renders; the base
`config.yaml` is the real file it is today.

## Capacity math (the real blocker for the future large model)

Serving host: the Mac Studio, 128 GB, ~118 GB wired ceiling.

**Current `nix-darwin` main residents** (`lib/hosts.nix`):

| Resident | Weights | KV cache |
| --- | --- | --- |
| `gpt-oss-120b-MXFP4-Q8` (default) | 63.3 GB | 6.0 GB |
| `Qwen3-Coder-30B-A3B-4bit` (coding) | 17.1 GB | 6.0 GB |
| **Resident total** | **80.4 GB** | **12.0 GB → 92.4 GB** |

Swap headroom under the 118 GB ceiling ≈ **25.6 GB**. The swap-tier
`Qwen3.6-35B-A3B-4bit` (20.4 GB + 3 GB cache) fits; OptiQ-4bit (~19.5 GB + cache)
fits and is served today via nix-ai auto-discovery.

Which large candidate fits alongside the 92.4 GB resident pair:

- **`gpt-oss-120b` (interim)** — already a resident, so **0 extra bytes**; it is
  the large phase at no memory cost.
- **`Qwen3-Next-80B-A3B-Thinking-4bit`** — 42 GB on disk. Does **not** fit:
  92.4 + 42 + cache ≈ 137 GB, well over the 118 GB ceiling. The auto-discover
  preflight (`disk × 1.3 = 54.6 GB > available`) even refuses to register it.

**This is the correction to the campaign brief.** The brief assumed residents of
`coder-30B + OptiQ ≈ 58.6 GB`, under which Next-80B (42 GB) fits. That is **not**
the deployed `nix-darwin` main config, which keeps `gpt-oss-120b` resident
(80.4 GB pair). Under the deployed config, **Next-80B cannot be served at all
without evicting a resident** — it is not a "swap-tier registration + llama-swap
handles it" job, because it does not fit the swap headroom.

So the interim large model is **`gpt-oss-120b`**, which is already resident, needs
**no `nix-darwin` change**, and is a genuinely different, larger brain than the
35B OptiQ — a real A/B at zero memory cost. Note the per-phase context differs and
is handled automatically: gpt-oss-120b = 131072, OptiQ = 262144 (both already in
the router alias table).

## Flagship-generation upgrade path (Next-80B and the 50–90 GB tier)

A large model that does not co-reside with the resident pair (Next-80B today, a
Qwopus-class 50–90 GB flagship later) needs a **serving-side** change first — this
rotation cannot conjure memory. In priority order:

1. **Reconcile the resident set in `nix-darwin` `lib/hosts.nix`.** Either drop
   `gpt-oss-120b` as resident (the brief's assumed `coder-30B + OptiQ` pair frees
   ~34 GB) so Next-80B fits as swap, **or** move to an llama-swap **group-swap**
   where the large brain and a resident are mutually exclusive (`groupSwap = true`
   is already a supported knob; it is off today precisely to keep both warm).
2. **Register the large model explicitly** in `lib/hosts.nix:mlx.models` with its
   own tool-call/reasoning parser args (Next-80B is `qwen3_next` — the early
   "batches crash" reputation is **retired** per `mlx-benchmarks` model-notes, but
   automatic prefix caching stays unsupported and MTP/spec-decode must stay off).
   Auto-discovery is not sufficient: discovered models inherit the **default**
   model's serve flags (gpt-oss's harmony parser), which is wrong for a Qwen brain.
3. **Add the first-class router alias** (one line in `llm_router_large_models`,
   `context_window: 262144`) so `ai-default` can resolve its backend + context.
4. Flip `ai_default_model_large` to the new id and converge.

The flagship generation therefore works as **night-model-resident / day-model-swap
via group-swap**, decided in `nix-darwin`; this repo's rotation is unchanged (it
only ever swaps which alias `ai-default` maps to).

## Failure modes and guards

- **Rotation fires during an active chat.** The `litellm` restart drops
  in-flight requests on the router tier only — not the agent session or its
  history — and clients retry. Accepted as the scheduled 00:00/12:00 blip.
  Hermes tolerates the underlying model changing between turns because each
  completion is stateless.
- **A managed bench window is active.** The large brain must not load and
  collide with a bench. `litellm-rotate-large.service` carries
  `ConditionPathExists=!<config_dir>/rotation-paused`; the bench runbook
  `touch`es that sentinel to keep the fabric on the optimized (small) brain,
  and should `systemctl start litellm-rotate-optimized` to flip down
  immediately if a bench begins mid-large-phase. Removing the sentinel resumes
  rotation at the next fire. No codified bench-window signal exists in the
  repos today, so this sentinel is the wiring point.
- **The large model fails to load.** llama-swap loads lazily on first request,
  so a bad large id surfaces as 500s on `ai-default` until 12:00. Documented
  follow-up (not in this PR): have the rotate-large oneshot warm and verify the
  model against the gate, reverting the symlink on failure.
- **A converge lands mid-phase.** The symlink target is computed from the
  guest's current UTC hour, so a converge always re-affirms the correct live
  phase instead of resetting it.
- **A phase id is not in the alias table.** The converge fails loud — the
  phase→backend/context resolution asserts membership in
  `llm_router_large_models`.

## Open questions for the gate

1. **Interim large = `gpt-oss-120b`?** It is the only zero-serving-change option.
   Confirm it is an acceptable agentic brain for the large phase, or accept that
   the A/B will expose its agentic tool-calling quality (OptiQ won the 2026-07-08
   bench; gpt-oss-120b was not in that field).
2. **Enable now or after serving reconcile?** Shipping disabled is safe and
   byte-identical. Flipping `ai_rotation_enabled: true` with the `gpt-oss-120b`
   interim works today; Next-80B needs the `nix-darwin` resident reconcile first.
3. **Per-guest rotation (3 routers, 3 timers) vs a single owner?** This design
   rotates per router guest (idempotent, resilient, no elected owner). All three
   bounce `litellm` within `AccuracySec` at the mark.
