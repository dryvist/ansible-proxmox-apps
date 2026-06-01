# plex

Plex Media Server, LAN-only (no VPN). Installs from Plex's official apt repo,
enables the bundled systemd service, scaffolds the `movies`/`tv` library roots,
and claims the server idempotently and non-fatally from a SOPS-sourced claim
token. Finishing the library "add" can still be done in the Plex web UI / API
after deploy.

## Installation

Provisioned by the `plex` LXC in `terraform-proxmox` (pve2, `tank/media`
bind-mount). Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags plex
```

## Requirements

- Debian-based LXC.
- `tank/media` bind-mounted at `/mnt/media`.

## Key variables

Server port comes from terraform (`terraform_data.constants.media_ports.plex_web`).
See `defaults/main.yml`.

- `plex_media_dir` — media library root (default `/mnt/media`).
- `plex_library_subdirs` — library subdirs scaffolded under it (`movies`, `tv`).
- `plex_apt_repo` — Plex apt repository line.
- `plex_web_port` — server/web UI port (terraform-derived).
- `plex_claim_token` — Plex claim token, read from `PLEX_CLAIM_TOKEN` (SOPS env).
- `plex_preferences_path` — `Preferences.xml` location (holds `PlexOnlineToken`).

## Server claim (idempotent + non-fatal)

`tasks/claim.yml` consumes a Plex claim token to link the server to your account,
the standard headless apt-install claim flow:

1. **Already claimed** — `Preferences.xml` has a non-empty `PlexOnlineToken` ⇒
   skip.
2. **Token present + valid** — exchange it at the local Plex API
   (`POST http://127.0.0.1:32400/myplex/claim?token=…`) for the permanent token.
3. **Token absent or expired** — log a clear reminder and **continue** (the play
   never fails on a missing/stale token).

> **Plex claim tokens expire ~4 minutes after generation**
> ([plex.tv/claim](https://www.plex.tv/claim)). A token stored in SOPS is almost
> always already stale by converge time. To automate the claim, generate a fresh
> token and drop it into `PLEX_CLAIM_TOKEN` in `secrets.enc.yaml`
> *immediately before* running the converge. Otherwise, claim once via the web
> UI at `http://<lxc-ip>:<plex_web_port>/web`.

## Secrets

| Variable           | Purpose                                      | Source                  |
| ------------------ | -------------------------------------------- | ----------------------- |
| `PLEX_CLAIM_TOKEN` | Fresh Plex claim token to auto-claim the PMS | SOPS `secrets.enc.yaml` |

`PLEX_CLAIM_TOKEN` is never committed. When unset or expired, the claim is
skipped non-fatally and the server can be claimed in the Plex web UI instead.

## Usage

```yaml
- name: Configure Plex Media Server
  hosts: plex_group
  become: true
  roles:
    - role: plex
```

With the SOPS env loaded so `PLEX_CLAIM_TOKEN` reaches the role:

```sh
sops exec-env secrets.enc.yaml 'doppler run -- \
  ansible-playbook playbooks/site.yml --tags plex'
```
