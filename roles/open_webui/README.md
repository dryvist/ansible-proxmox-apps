# open_webui

Deploys **Open WebUI** (CT 168 `hermes-chat`) as the chat front-end for the local
LLM, talking to **Ollama** (CT 167) and fronted by **Traefik** at
`https://llm.<PROXMOX_SUBDOMAIN>` (e.g. `https://llm.pve.jacobpevans.com`).

## Installation

Ships with the `ansible-proxmox-apps` repo; no external install. The container is
provisioned by `terraform-proxmox`. This role is wired into `playbooks/site.yml`
against the `open_webui_group` (containers tagged `open-webui` in the tofu
inventory) and runs over the `proxmox_pct_remote` connection. Tools come from the
repo's Nix dev shell (`direnv allow`). Deploy after the `ollama` role (its backend).

Requires `OPEN_WEBUI_SECRET_KEY` in Doppler/SOPS (generate once: `openssl rand -hex 32`).

## What it does

- Creates an `open-webui` system user, installs `curl`/`ca-certificates`/`sudo`
  (a minimal LXC template lacks them — curl for the uv installer, sudo for the
  `become_user` privilege drop), then **uv**.
- Installs Open WebUI into a venv (`/opt/open-webui/venv`) and runs it via a
  dedicated systemd unit (`open-webui serve`), data in `DATA_DIR=/var/lib/open-webui`.
- Renders `/etc/open-webui.env` with the **reverse-proxy-correct** settings Open
  WebUI requires behind HTTPS: `OLLAMA_BASE_URL` (→ CT 167, from inventory),
  `WEBUI_URL`/`CORS_ALLOW_ORIGIN` (= the Traefik URL, from `PROXMOX_SUBDOMAIN`),
  secure cookies, `ENABLE_WEBSOCKET_SUPPORT`, stable `WEBUI_SECRET_KEY`.
- Restart-on-failure via the shared `systemd_restart_policy` role (`group_vars`).

## Key variables (`defaults/main.yml`)

| Var | Default | Purpose |
| --- | --- | --- |
| `open_webui_port` | `tofu_data.constants.service_ports.open_webui_web` | Listen port (no hardcode) |
| `open_webui_ollama_base_url` | `http://<hermes-infer ip>:<ollama_api>` | Backend (from inventory) |
| `open_webui_hostname` | `llm.{{ PROXMOX_SUBDOMAIN }}` | Public FQDN via Traefik |
| `open_webui_data_dir` | `/var/lib/open-webui` | Persistent data |
| `open_webui_secret_key` | `OPEN_WEBUI_SECRET_KEY` (Doppler/SOPS) | Stable JWT/encryption key |

## Usage

```bash
env -u DOPPLER_PROJECT -u DOPPLER_CONFIG -u DOPPLER_ENVIRONMENT \
  sops exec-env secrets.enc.yaml 'doppler run -- \
  ./scripts/run-ansible.sh playbooks/site.yml --limit hermes-chat --tags open_webui,ai'
```

## Verify

```bash
pct exec 168 -- curl -fsS http://127.0.0.1:8080/health   # service up (LAN)
# then browse https://llm.<subdomain> (after the Traefik ingress entry is live)
```
