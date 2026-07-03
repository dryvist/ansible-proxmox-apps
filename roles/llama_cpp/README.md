# llama_cpp

Deploys the **light serving tier**: [llama.cpp](https://github.com/ggml-org/llama.cpp)
(`llama-server`) behind [llama-swap](https://github.com/mostlygeek/llama-swap) on an
AMD **ROCm** GPU, inside a privileged LXC (guest `llm-fast`, RX 6800 = gfx1030).
llama-swap presents **one** OpenAI-compatible endpoint and keeps the configured
models co-resident, so Hermes-4-14B + a small general model + an embeddings model
all fit in 16 GB at Q4 and answer without reload churn.

## Installation

Ships with the `ansible-proxmox-apps` repo; no external install. The container is
provisioned by `terraform-proxmox` and the GPU device nodes (`/dev/kfd`, `/dev/dri`)
are passed in by `ansible-proxmox` (role `lxc_gpu_features`) — both must be in place
first. Wired into `playbooks/site.yml` against `llm_fast_group` (guests tagged
`llm-fast` in the tofu inventory). Tools come from the repo's Nix dev shell
(`direnv allow`).

Ordering: `terraform-proxmox` (LXC shell) → `ansible-proxmox` (GPU passthrough) →
**this role** (llama.cpp + llama-swap + models) → `llm_router` (LiteLLM front door).

## What it does

- Installs `curl`, `ca-certificates`, `tar`, `gzip`.
- Resolves and installs the **latest** llama.cpp release (the `ubuntu-rocm` asset,
  selected by name pattern so both the build tag and the embedded ROCm version can
  move without a role change) and the **latest** llama-swap release, each once
  behind a presence guard.
- Adds the `llama-cpp` service user to whatever groups own the passed-in GPU device
  nodes (resolved at runtime via `stat`), so the server can open `/dev/kfd` +
  `/dev/dri` regardless of how host GIDs map to container group names (same idiom as
  `roles/ollama`).
- Stages the model GGUFs as local files (downloads only when absent).
- Renders the llama-swap config (a co-resident model group) + a systemd unit,
  listening on `service_ports.llm_fast_api`. Restart-on-failure is applied by the
  shared `systemd_restart_policy` role via `group_vars/llm_fast_group.yml`.

## Models

| model_name | aliases | kind |
| --- | --- | --- |
| `hermes-4-14b` | `hermes4` | chat (`--jinja`) |
| `qwen3-4b` | — | chat (`--jinja`) |
| `embeddings` | `nomic-embed-text-v1.5` | `--embeddings` |

All three are members of the `resident` llama-swap group (`swap: false`), so they
stay loaded together.

## GPU toggle

`llama_cpp_gpu: true` (default) builds the ROCm path: all layers offloaded
(`-ngl 99`), `HSA_OVERRIDE_GFX_VERSION=10.3.0` for gfx1030. Setting it `false` (for a
future CPU-only `llm-light` standby guest) skips every ROCm/GPU task, runs `-ngl 0`
with a smaller context, and drops the GPU env from the unit.

## Key variables (`defaults/main.yml`)

| Var | Default | Purpose |
| --- | --- | --- |
| `llama_cpp_api_port` | `tofu_data.constants.service_ports.llm_fast_api` | llama-swap listen port (no hardcode) |
| `llama_cpp_gpu` | `true` | ROCm GPU vs CPU-only standby |
| `llama_cpp_models` | 3-model list | served models + GGUF sources |
| `llama_cpp_install_dir` | `/opt/llama-cpp` | binary + bundled ROCm `.so` files (also `LD_LIBRARY_PATH`) |
| `llama_cpp_models_dir` | `/var/lib/llama-cpp/models` | staged GGUFs (persistent volume) |
| `llama_cpp_rocm_packages` | `[]` | best-effort container ROCm runtime packages |

## Usage

```bash
# Deploy (after terraform + ansible-proxmox GPU passthrough)
env -u DOPPLER_PROJECT -u DOPPLER_CONFIG -u DOPPLER_ENVIRONMENT doppler run -- \
  ./scripts/run-ansible.sh playbooks/site.yml --limit llm-fast --tags llama_cpp,ai
```

## Not yet live-validated

Verify on the first converge (W6): (a) the prebuilt ROCm llama.cpp binary runs
against the container's ROCm userspace (it is dynamically linked to the ROCm runtime
— the LXC must provide it; see `llama_cpp_rocm_packages`); (b)
`HSA_OVERRIDE_GFX_VERSION=10.3.0` is honoured by the release build for gfx1030; (c)
the GGUF asset filenames still resolve on HuggingFace.
