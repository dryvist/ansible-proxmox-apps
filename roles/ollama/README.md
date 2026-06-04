# ollama

Deploys **Ollama** as the local LLM inference server on an AMD **ROCm** GPU,
inside an LXC (CT 167 `hermes-infer`, RX 6800), and provisions **Hermes 4 14B**.

## Installation

Ships with the `ansible-proxmox-apps` repo; no external install. The container is
provisioned by `terraform-proxmox` and the GPU device nodes (`/dev/kfd`,
`/dev/dri`) are passed in by `ansible-proxmox` (role `lxc_gpu_features`) — both
must be in place first. This role is wired into `playbooks/site.yml` against the
`ollama_group` (containers tagged `ollama` in the tofu inventory). Tools come
from the repo's Nix dev shell (`direnv allow`).

Ordering: `terraform-proxmox` (LXC shell) → `ansible-proxmox` (GPU passthrough) →
**this role** (Ollama + ROCm + model) → `open_webui` (chat UI).

## What it does

- Installs Ollama via the official script (creates the `ollama` user + systemd unit).
- Overlays the **ROCm runtime** tarball (the installer ships CPU/NVIDIA libs only).
- Creates `render`/`video` groups at the host GIDs and adds `ollama` to them so the
  service can open `/dev/kfd` + `/dev/dri`.
- Writes a systemd env drop-in (`OLLAMA_HOST`, `OLLAMA_MODELS`,
  `HSA_OVERRIDE_GFX_VERSION=10.3.0` for gfx1030, flash-attention, keep-alive).
- Pulls **Hermes 4 14B** Q4_K_M GGUF from HuggingFace and aliases it to `hermes4`.
- Restart-on-failure is applied by the shared `systemd_restart_policy` role via
  `group_vars/ollama_group.yml`.

## Key variables (`defaults/main.yml`)

| Var | Default | Purpose |
| --- | --- | --- |
| `ollama_api_port` | `tofu_data.constants.service_ports.ollama_api` | API port (no hardcode) |
| `ollama_models_dir` | `/var/lib/ollama` | Model store (120 GB local-zfs vol) |
| `ollama_hsa_override_gfx_version` | `10.3.0` | RX 6800 / Navi 21 / gfx1030 |
| `ollama_model_name` | `hermes4` | Local alias |
| `ollama_model_source` | `hf.co/bartowski/NousResearch_Hermes-4-14B-GGUF:Q4_K_M` | GGUF source |

## Usage

```bash
# Deploy (after terraform + ansible-proxmox GPU passthrough)
env -u DOPPLER_PROJECT -u DOPPLER_CONFIG -u DOPPLER_ENVIRONMENT doppler run -- \
  ./scripts/run-ansible.sh playbooks/site.yml --limit hermes-infer --tags ollama,ai
```

## Verify

```bash
pct exec 167 -- rocminfo | grep -i gfx            # GPU visible to ROCm
pct exec 167 -- ollama run hermes4 "say hi"        # GPU inference (watch radeontop)
curl http://10.0.40.167:11434/v1/models            # OpenAI-compatible endpoint
```
