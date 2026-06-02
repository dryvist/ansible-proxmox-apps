# plex

Plex Media Server, LAN-only (no VPN). Installs from Plex's official apt repo,
enables the bundled systemd service, scaffolds the `movies`/`tv` library roots,
claims the server idempotently and non-fatally from a SOPS-sourced claim token,
and (given an account token) creates the `Movies` + `TV` library sections so
imported media is visible — including on Roku.

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
- `plex_account_token` — Plex account X-Plex-Token, read from `PLEX_TOKEN` (SOPS
  env); required to auto-create library sections.
- `plex_libraries` — library sections to ensure exist (name/type/location/agent).
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

## Library creation (idempotent + non-fatal)

`tasks/libraries.yml` turns the scaffolded dirs into real Plex library sections —
without a section, imported media never appears (incl. on Roku). It needs an
account-scoped `X-Plex-Token` (the ~4-min claim token is not enough):

1. **Token unset** — log the manual step and skip (never fatal).
2. **Token set** — `GET /library/sections`, then `POST` only the missing sections
   (`Movies` → `/mnt/media/movies`, `TV` → `/mnt/media/tv`).
3. **Server not yet claimed / stale token** — the `POST` returns 4xx; logged,
   not fatal. Claim the server, then re-run.

## Secrets

| Variable           | Purpose                                      | Source                  |
| ------------------ | -------------------------------------------- | ----------------------- |
| `PLEX_CLAIM_TOKEN` | Fresh Plex claim token to auto-claim the PMS | SOPS `secrets.enc.yaml` |
| `PLEX_TOKEN`       | Account X-Plex-Token to create libraries     | SOPS / Doppler          |

Neither is committed. When `PLEX_CLAIM_TOKEN` is unset/expired the claim is
skipped non-fatally (claim via the web UI). When `PLEX_TOKEN` is unset, library
creation is skipped (add libraries via the web UI).

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
