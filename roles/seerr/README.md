# seerr

Runs [Seerr](https://github.com/seerr-team/seerr) (the self-hosted
movie/TV request UI) as a single Docker container on a dedicated
Docker-in-LXC (`seerr`, LXC 214), publishes the web UI on the
Terraform-derived port (`media_ports.seerr_web` = 5055), persists its
config to a host directory, and registers Sonarr + Radarr (and optionally
Plex) via the Seerr settings API.

This role mirrors the `idrac_kvm_docker` Docker-in-LXC pattern: install Docker
CE + Compose, `fuse-overlayfs` for ZFS-backed LXC, a Python venv for the
`community.docker` modules, then a one-container Compose project.

Seerr is **config-only** — it has no `/tank` bind-mounts and reaches the
`*arr` apps + Plex over the LAN.

## Installation

Wired into `playbooks/site.yml` (Phase 8c, media stack) against any host in
`seerr_group`. The group is populated by `inventory/load_terraform.yml`
from `containers` tagged `seerr` in the Terraform inventory (terraform-proxmox
LXC 214 `seerr`), reached over `proxmox_pct_remote`.

Prerequisites:

- LXC 214 `seerr` exists (Terraform-managed; tags include `container`,
  `media`, `seerr`; `nesting=true` for Docker).
- SOPS `secrets.enc.yaml` populated with `SEERR_API_KEY` (and, to register
  the `*arr` apps, `SONARR_API_KEY` / `RADARR_API_KEY`). Generate each with
  `openssl rand -hex 16` (32 hex chars).

Install the collection dependencies once:

```sh
ansible-galaxy collection install -r requirements.yml
```

## Usage

```sh
# From the repo root, with SOPS env + Doppler loaded:
sops exec-env secrets.enc.yaml 'doppler run -- \
  ansible-playbook playbooks/site.yml --tags seerr'
```

The role asserts `SEERR_API_KEY` is set before doing any work and fails
fast with a pointer to SOPS if it is missing.

## Access

After a successful run on LXC 214:

| Service | URL                          | Container |
| ------- | ---------------------------- | --------- |
| Seerr   | `http://<lxc-214-ip>:5055/`  | `seerr`   |

## Deterministic API key

The Seerr API key normally auto-generates on first start. This role seeds
it deterministically so downstream tooling knows it before the container runs:

- `templates/settings.json.j2` writes a minimal `settings.json` with
  `main.apiKey` set from `SEERR_API_KEY`. It is a **one-time seed**
  (`force: false`, mode `0640`): Seerr owns and rewrites `settings.json`
  at runtime, so the role never clobbers live state on subsequent runs.

## Service registration (Sonarr / Radarr / Plex)

`tasks/register.yml` registers the `*arr` apps idempotently and self-healingly
via the Seerr settings API (GET-then-PUT-always — the repo's house pattern,
no bespoke scripts):

- `GET /api/v1/settings/{radarr,sonarr}` to read existing servers.
- Resolve the target app's first quality-profile id from its own
  `/api/v3/qualityprofile` (Seerr requires `activeProfileId`).
- `POST` the server only when no entry with that hostname exists yet.
- `PUT /api/v1/settings/{radarr,sonarr}/{id}` to reconcile an existing entry
  whenever its stored `apiKey`, `port`, or `useSsl` drifts from the SOPS-sourced
  value. A converged host PUTs nothing; a SOPS key rotation re-syncs the entry.

This makes the role re-runnable at **any** point: a rotated `SONARR_API_KEY` /
`RADARR_API_KEY` is pushed into Seerr's DB on the next converge instead of
leaving a stale key behind a 401.

Hostnames default to the media-stack LXC IPs from inventory; ports come from
Terraform constants. Sonarr/Radarr registration is skipped if its API key is
unset.

### Plex + owner sign-in

Seerr's settings endpoints require the **owner** user, which only exists
after a Plex sign-in. `register.yml` discovers the Plex account token
(`PlexOnlineToken`) from the **claimed** server's `Preferences.xml` (no token has
to be supplied; `PLEX_TOKEN` is an optional override), signs the owner in via
`POST /api/v1/auth/plex`, then registers Sonarr/Radarr and links Plex
(`/api/v1/settings/plex` + library sync).

- **Plex claimed**: the owner is created and Sonarr/Radarr/Plex are wired
  automatically.
- **Plex not claimed**: there is no token to discover, so registration is
  **skipped non-fatally** with a reminder — claim Plex, then re-run (or finish in
  the Seerr UI). This is **off the path to watching on Roku** — Plex serves
  Roku directly.

> Jellyseerr 2.7.x regenerates its own API key on first init, so `register.yml`
> reads the **live** key from `settings.json` for its API calls rather than the
> seeded `SEERR_API_KEY` (which only seeds the file before first start).

## How it's built

- `defaults/main.yml` — image, ports (from Terraform constants), config dir,
  API key + service-registration variables, `seerr_manage_services`
  toggle (false in Molecule).
- `templates/docker-compose.yml.j2` — one `seerr` service, binds
  `<bind_address>:<web_port>:5055`, mounts the host config dir to `/app/config`.
- `templates/settings.json.j2` — one-time API-key seed.
- `tasks/main.yml` — API-key assertion → Docker install → venv → data dirs →
  settings seed → compose deploy → port + HTTP health check → service
  registration.
- `tasks/register.yml` — idempotent Sonarr/Radarr (and optional Plex)
  registration via the Seerr settings API.

## Secrets

| Variable         | Purpose                                        | Source                  |
| ---------------- | ---------------------------------------------- | ----------------------- |
| `SEERR_API_KEY`  | Deterministic Seerr API key (32 hex)           | SOPS `secrets.enc.yaml` |
| `SONARR_API_KEY` | Sonarr API key (to register Sonarr in Seerr)   | SOPS `secrets.enc.yaml` |
| `RADARR_API_KEY` | Radarr API key (to register Radarr in Seerr)   | SOPS `secrets.enc.yaml` |
| `PLEX_TOKEN`     | Optional account X-Plex-Token to link Plex     | SOPS `secrets.enc.yaml` |

None are ever committed to git. The role's first task asserts
`SEERR_API_KEY` is set and fails fast with a pointer to SOPS.
