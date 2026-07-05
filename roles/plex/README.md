# plex

Plex Media Server, LAN-only (no VPN). Installs from Plex's official apt repo,
enables the bundled systemd service, scaffolds the `movies`/`tv` library roots,
claims the server idempotently and non-fatally from a SOPS-sourced claim token,
and (given an account token) creates the `Movies` + `TV` library sections so
imported media is visible — including on Roku.

## Installation

Provisioned by the `plex` LXC in `terraform-proxmox` (single
`bulk/data` bind-mount at `/data`). Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags plex
```

## Requirements

- Debian-based LXC.
- The single `bulk/data` dataset bind-mounted at `/data` (TRaSH
  single-filesystem layout); libraries read `/data/media/{movies,tv}`.

## Key variables

Server port comes from OpenTofu (`tofu_data.constants.media_ports.plex_web`).
See `defaults/main.yml`.

- `plex_media_dir` — media library root (default `/data/media`).
- `plex_library_subdirs` — library subdirs scaffolded under it (`movies`, `tv`).
- `plex_apt_repo` — Plex apt repository line.
- `plex_web_port` — server/web UI port (tofu-derived).
- `plex_claim_token` — Plex claim token, read from `PLEX_CLAIM_TOKEN` (SOPS env).
- `plex_account_token` — Plex account X-Plex-Token, read from `PLEX_TOKEN`
  (environment); required to auto-create library sections.
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
> ([plex.tv/claim](https://www.plex.tv/claim)), so they are **never stored** in
> SOPS/secrets. Two ways to claim:
>
> - **Web UI** — sign in once at `http://<lxc-ip>:<plex_web_port>/web`.
> - **Ad-hoc converge** — generate a fresh token and pass it straight to the run:
>   `… ansible-playbook … --tags plex -e plex_claim_token=claim-XXXX`.

## Library creation (idempotent + non-fatal)

`tasks/libraries.yml` turns the scaffolded dirs into real Plex library sections —
without a section, imported media never appears (incl. on Roku). No token has to
be supplied: it works in whichever state the server is in.

1. **Claimed server** — discovers the account token (`PlexOnlineToken`) from
   `Preferences.xml`, then `GET /library/sections` and `POST` only the missing
   sections (`Movies` → `/data/media/movies`, `Shows` → `/data/media/tv`).
2. **Unclaimed server** — the local API accepts unauthenticated localhost
   requests, so the sections are created **token-free**; they persist after you
   later claim it.

`PLEX_TOKEN` is honoured as an optional override but is rarely needed.

## Secrets

No Plex token is stored. Claiming is a one-time account action (web UI, or an
ad-hoc `-e plex_claim_token=…` as above); the account token is then
auto-discovered from the server. `PLEX_TOKEN` (env) is an optional override only.

## Usage

```yaml
- name: Configure Plex Media Server
  hosts: plex_group
  become: true
  roles:
    - role: plex
```

With the secrets env loaded so `PLEX_TOKEN` (and, for a fresh claim,
`PLEX_CLAIM_TOKEN` passed via `-e`) reach the role:

```sh
sops exec-env secrets.enc.yaml 'doppler run -- ./scripts/fetch-openbao-secrets.sh media -- \
  ansible-playbook playbooks/site.yml --tags plex'
```
