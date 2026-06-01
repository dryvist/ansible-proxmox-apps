# jellyseerr

Runs [Jellyseerr](https://github.com/fallenbagel/jellyseerr) (the self-hosted
movie/TV request UI) as a single Docker container on a dedicated
Docker-in-LXC (`jellyseerr`, LXC 214), publishes the web UI on the
Terraform-derived port (`media_ports.jellyseerr_web` = 5055), persists its
config to a host directory, and registers Sonarr + Radarr (and optionally
Plex) via the Jellyseerr settings API.

This role mirrors the `idrac_kvm_docker` Docker-in-LXC pattern: install Docker
CE + Compose, `fuse-overlayfs` for ZFS-backed LXC, a Python venv for the
`community.docker` modules, then a one-container Compose project.

Jellyseerr is **config-only** — it has no `/tank` bind-mounts and reaches the
`*arr` apps + Plex over the LAN.

## Installation

Wired into `playbooks/site.yml` (Phase 8c, media stack) against any host in
`jellyseerr_group`. The group is populated by `inventory/load_terraform.yml`
from `containers` tagged `jellyseerr` in the Terraform inventory (terraform-proxmox
LXC 214 `jellyseerr`), reached over `proxmox_pct_remote`.

Prerequisites:

- LXC 214 `jellyseerr` exists (Terraform-managed; tags include `container`,
  `media`, `jellyseerr`; `nesting=true` for Docker).
- SOPS `secrets.enc.yaml` populated with `JELLYSEERR_API_KEY` (and, to register
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
  ansible-playbook playbooks/site.yml --tags jellyseerr'
```

The role asserts `JELLYSEERR_API_KEY` is set before doing any work and fails
fast with a pointer to SOPS if it is missing.

## Access

After a successful run on LXC 214:

| Service    | URL                          | Container    |
| ---------- | ---------------------------- | ------------ |
| Jellyseerr | `http://<lxc-214-ip>:5055/`  | `jellyseerr` |

## Deterministic API key

The Jellyseerr API key normally auto-generates on first start. This role seeds
it deterministically so downstream tooling knows it before the container runs:

- `templates/settings.json.j2` writes a minimal `settings.json` with
  `main.apiKey` set from `JELLYSEERR_API_KEY`. It is a **one-time seed**
  (`force: false`, mode `0640`): Jellyseerr owns and rewrites `settings.json`
  at runtime, so the role never clobbers live state on subsequent runs.

## Service registration (Sonarr / Radarr / Plex)

`tasks/register.yml` registers the `*arr` apps idempotently and self-healingly
via the Jellyseerr settings API (GET-then-PUT-always — the repo's house pattern,
no bespoke scripts):

- `GET /api/v1/settings/{radarr,sonarr}` to read existing servers.
- Resolve the target app's first quality-profile id from its own
  `/api/v3/qualityprofile` (Jellyseerr requires `activeProfileId`).
- `POST` the server only when no entry with that hostname exists yet.
- `PUT /api/v1/settings/{radarr,sonarr}/{id}` to reconcile an existing entry
  whenever its stored `apiKey`, `port`, or `useSsl` drifts from the SOPS-sourced
  value. A converged host PUTs nothing; a SOPS key rotation re-syncs the entry.

This makes the role re-runnable at **any** point: a rotated `SONARR_API_KEY` /
`RADARR_API_KEY` is pushed into Jellyseerr's DB on the next converge instead of
leaving a stale key behind a 401.

Hostnames default to the media-stack LXC IPs from inventory; ports come from
Terraform constants. Sonarr/Radarr registration is skipped if its API key is
unset.

### Plex (manual / optional)

Plex registration needs an **account-scoped Plex token** (`plex.tv` auth /
claim token), which cannot be derived from infrastructure. By default
(`PLEX_CLAIM_TOKEN` unset) the role **skips** Plex and logs a reminder. Two
options:

1. **Manual (default)**: link Plex in the Jellyseerr UI → Settings → Plex
   after deploy.
2. **Automated**: populate `PLEX_CLAIM_TOKEN` in SOPS and extend
   `register.yml` to `POST /api/v1/settings/plex`. The variable
   `jellyseerr_plex_token` already reads it.

## How it's built

- `defaults/main.yml` — image, ports (from Terraform constants), config dir,
  API key + service-registration variables, `jellyseerr_manage_services`
  toggle (false in Molecule).
- `templates/docker-compose.yml.j2` — one `jellyseerr` service, binds
  `<bind_address>:<web_port>:5055`, mounts the host config dir to `/app/config`.
- `templates/settings.json.j2` — one-time API-key seed.
- `tasks/main.yml` — API-key assertion → Docker install → venv → data dirs →
  settings seed → compose deploy → port + HTTP health check → service
  registration.
- `tasks/register.yml` — idempotent Sonarr/Radarr (and optional Plex)
  registration via the Jellyseerr settings API.

## Secrets

| Variable             | Purpose                                            | Source                  |
| -------------------- | -------------------------------------------------- | ----------------------- |
| `JELLYSEERR_API_KEY` | Deterministic Jellyseerr API key (32 hex)          | SOPS `secrets.enc.yaml` |
| `SONARR_API_KEY`     | Sonarr API key (to register Sonarr in Jellyseerr)  | SOPS `secrets.enc.yaml` |
| `RADARR_API_KEY`     | Radarr API key (to register Radarr in Jellyseerr)  | SOPS `secrets.enc.yaml` |
| `PLEX_CLAIM_TOKEN`   | Optional Plex token to automate Plex registration  | SOPS `secrets.enc.yaml` |

None are ever committed to git. The role's first task asserts
`JELLYSEERR_API_KEY` is set and fails fast with a pointer to SOPS.
