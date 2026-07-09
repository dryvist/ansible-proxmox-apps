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
ai_rotation_enabled: false                                 # master switch
ai_default_model_optimized: Qwen3.6-35B-A3B-OptiQ-4bit     # 12:00 UTC brain
ai_default_model_large: Qwen3-Next-80B-A3B-Thinking-4bit   # 00:00 UTC brain
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

## Capacity math

Serving host: the Mac Studio, 128 GB, ~118 GB wired ceiling, ~109 GB cache-clear
trip (`gpuMemoryUtilization 0.80`).

**Current `nix-darwin` main residents** (`lib/hosts.nix`, release 1.73.0 / #1589):

| Resident | Weights | KV cache |
| --- | --- | --- |
| `Qwen3-Coder-30B-A3B-4bit` (coding) | 17.1 GB | 6.0 GB |
| `Qwen3.6-35B-A3B-OptiQ-4bit` (tool-calling) | 19.5 GB | 16.0 GB |
| **Resident total** | **36.6 GB** | **22.0 GB → 58.6 GB** |

`gpt-oss-120b` is **no longer preloaded** (it failed the agentic gate at 0%): it
drops to on-demand and idle-unloads. Auto-discovery is force-disabled fleet-wide
(`hosts/common/mlx-no-autodiscover.nix`), so every swap model is registered
explicitly.

**The large phase (`Qwen3-Next-80B-A3B-Thinking-4bit`) does NOT fit the swap
tier alongside both residents** — the original estimate here (58.6 GB residents
+ ~42 GB weights + 4 GB cache ≈ 104.6 GB, under the ~109 GB trip) budgeted only
weights + configured cache. The first live large phase (2026-07-09 00:00 UTC)
measured Next-80B's real per-process peak at **51.5 GB** (scheduler
`[Metal memory] ... peak=51.5GB` — activations and paged-cache overshoot on top
of ~46 GB), putting the composition at ~109.5 GB ≥ the trip: all three backends
crashed (`upstream exited unexpectedly`) within 33 minutes. Budget large-phase
capacity from **measured peak**, not weights + cache. The cache is deliberately
kept small (4 GB); the model
idle-unloads at 900 s back to the 58.6 GB baseline. It is registered in
`lib/hosts.nix:mlx.models` (see the companion nix-darwin PR), **not** auto-
discovered — a discovered model would inherit the default model's serve flags
(wrong parser for a Qwen brain).

**Why not `gpt-oss-120b` as the large brain?** It is the biggest local model, but
it scored **0% valid agentic tool calls** in the 2026-07-08 grid, so serving it as
Hermes's brain 12h/day would lobotomize tool-calling — the exact regression the
A/B is meant to surface, not cause. Next-80B benched 100% valid (single run,
provisional), degrades ~round 17, ~12 tok/s. Both rotation phases carry a 262144
context, so the `ai-default` alias's `max_input_tokens` is identical across the
flip.

## Flagship-generation upgrade path (the 50–90 GB tier)

A future large brain (a Qwopus-class 50–90 GB flagship) that does **not** co-reside
with the 58.6 GB resident pair under the ~109 GB trip needs a **serving-side**
change first — this rotation cannot conjure memory. In priority order:

1. **Reconcile the resident set / swap policy in `nix-darwin` `lib/hosts.nix`.**
   Either trim a resident (or its cache) to free room for the flagship as swap, or
   move to an llama-swap **group-swap** where the flagship and a resident are
   mutually exclusive (`groupSwap = true` is already a supported knob; it is off
   today to keep both brains warm).
2. **Register the flagship explicitly** in `lib/hosts.nix:mlx.models` with its own
   tool-call/reasoning parser args (the Next-80B entry is the worked example: the
   `qwen3_next` "batches crash" reputation is **retired** per `mlx-benchmarks`
   model-notes, but automatic prefix caching stays unsupported and MTP/spec-decode
   must stay off). Auto-discovery is force-disabled, so registration is mandatory.
3. **Add the first-class router alias** (one line in `llm_router_large_models`,
   `context_window: 262144`) so `ai-default` can resolve its backend + context.
4. Flip `ai_default_model_large` to the new id and converge.

The flagship generation is decided in `nix-darwin` (resident/swap policy); this
repo's rotation is unchanged — it only ever swaps which alias `ai-default` maps to.

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

## Incident 2026-07-09: first live large phase (paused pending gates)

The rotation's first large phase caused a production outage and the rotation is
now **paused** (sentinel present on all three routers, fabric held on the
optimized brain). Two independent causes, both evidence-backed:

1. **Memory overcommit → backend crashes (00:33 UTC).** See the corrected
   capacity math above: Next-80B's measured 51.5 GB peak pushed the composition
   to ~109.5 GB ≥ the ~109 GB trip. OptiQ crashed twice and Coder once
   (`upstream exited unexpectedly`); the crash/restart cycle then wedged
   `llama-swap`'s routing (backends health-checked "ready" but zero requests
   forwarded for ~70 minutes) until a full serving restart.
2. **Throughput below the cron fleet's floor.** One production generation took
   **40m51s** (3.4 MB response) — past the router's 2400 s per-attempt timeout
   and the client's 1800 s budget — with a 6-deep queue behind it
   (`maxNumSeqs 2`). At Next-80B's under-load decode rate the scheduled sweep
   fleet saturates it permanently, so every large-phase cron fails even when
   nothing crashes.

**Re-enable gates** (in addition to "Open questions" below): a large brain must
(a) fit under the trip using its **measured** per-process peak alongside
whatever stays resident, and (b) sustain the cron fleet — its under-load decode
rate must complete the fleet's typical generation (~15–20k tokens) inside the
client's 1800 s stream budget with the fleet's concurrency, i.e. ≥ ~10 tok/s
per stream **sustained at its real queue depth**, which Next-80B does not meet
today (40m51s ≈ 7–8 tok/s effective on one stream while queueing five more).
Until a candidate passes both, `rotation-paused` stays.

**Operational note — restarting the serving stack:** `launchctl kickstart -k
gui/<uid>/dev.vllm-mlx.server` kills only `llama-swap`; the `vllm-mlx serve`
children survive as orphans squatting their ports, and the fresh `llama-swap`
health-checks those orphans "ready" while unable to manage them. Always
`pkill -f "vllm-mlx serve"` (escalate to `-9`) before the kickstart.

## Open questions for the gate

1. **Enable sequencing.** Shipping disabled is safe and byte-identical. Enabling
   the rotation requires, in order: merge the companion `nix-darwin` PR (Next-80B
   swap registration) → rebuild jevans-ms → a live load test of the `ai-default`
   alias flip (confirm Next-80B swaps in under the trip and serves tool calls) →
   flip `ai_rotation_enabled: true` and converge.
2. **Bench maturity.** Next-80B's 100%-valid agentic result is a single,
   provisional run. If the maturity policy (≥4 runs, both environment classes)
   later demotes it, the large-phase id is a one-line change here + a swap entry
   in `nix-darwin`.
3. **Per-guest rotation (3 routers, 3 timers) vs a single owner?** This design
   rotates per router guest (idempotent, resilient, no elected owner). All three
   bounce `litellm` within `AccuracySec` at the mark.
