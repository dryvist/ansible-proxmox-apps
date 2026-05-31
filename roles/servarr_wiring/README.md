# servarr_wiring

Idempotent **Servarr API self-wiring**: a single converge auto-configures the
Prowlarr ↔ Sonarr/Radarr ↔ qBittorrent pipeline so the media stack is
"hands-off" after deploy. No clicking through web UIs.

This role runs **after** the apps are installed (`download_vpn` provides
Prowlarr + qBittorrent; `sonarr` / `radarr` provide the PVRs) and wires them
together over the LAN.

## What it does (all idempotent — GET-then-POST/PUT)

1. **Deterministic API keys** — sets `<ApiKey>` in each app's `config.xml`
   (Sonarr `/var/lib/sonarr`, Radarr `/var/lib/radarr`, Prowlarr
   `/var/lib/prowlarr`) from SOPS env, delegated to each app's host. Restarts
   the app and waits for its API only when the key actually changed. Templating
   the key means every cross-app reference is known **before** converge instead
   of being auto-generated.
2. **Prowlarr → Sonarr/Radarr Applications** — adds each as a Prowlarr
   Application with sync level `fullSync`, so Prowlarr pushes its indexers to
   both. Schema-driven: the role GETs `/api/v1/applications/schema`, overrides
   only `prowlarrUrl` / `baseUrl` / `apiKey`, and POSTs if absent.
3. **Sonarr/Radarr → qBittorrent download client** — adds qBittorrent (host =
   `download-vpn`, port = `media_ports.qbittorrent_web`, category `tv` /
   `movies`) to each PVR, again schema-driven.
4. **Root folders** — ensures `/mnt/media/tv` (Sonarr) and `/mnt/media/movies`
   (Radarr).
5. **Completed-download handling** — enables it globally on each PVR.

## Why `ansible.builtin.uri` and not a community role / Buildarr

A search-first pass (logged in the PR) found the community Servarr Ansible
roles (`tinyoverflow`, `coaxial`, `Amixp`, `sleepy_nols`) are **install-only**
— none do cross-app API wiring. Declarative tools (Buildarr, Recyclarr,
Configarr) **do** wire apps, but each is an **external daemon / cron job**
(Docker or Python) that lives outside the Ansible converge model and would add
a new always-running config layer to an LXC-native homelab. The repo already
has a vetted house pattern for idempotent API config — `ansible.builtin.uri`
GET-then-POST, used by the merged `download_vpn` role for qBittorrent — so this
role follows it. Buildarr remains the documented future option if declarative
drift-correction becomes desirable (see the PR's open-questions).

## Quality profiles

Sonarr and Radarr **ship default quality profiles** (Any, SD, HD-720p,
HD-1080p, Ultra-HD, …) seeded on first run. This role does not POST a redundant
profile — that would fight the app's own defaults. The `jellyseerr` role
resolves a valid `activeProfileId` from each PVR's existing
`/api/v3/qualityprofile` when it registers the server. Override the chosen
profile in the UI or extend this role if a custom profile is required.

## Indexers (manual / SOPS step — NOT automated here)

The role scaffolds the Prowlarr **Application sync** but deliberately does
**not** add indexer *definitions*. Private trackers need per-user credentials
(cookies, passkeys, API tokens) that are account-scoped and cannot be derived
from infrastructure. Add indexers one of two ways:

1. **Manual**: Prowlarr UI → Indexers → add your trackers. Prowlarr's
   `fullSync` Application then pushes them to Sonarr/Radarr automatically.
2. **SOPS-driven (future)**: store each tracker's credentials in
   `secrets.enc.yaml` and extend this role with a `prowlarr_indexers.yml`
   schema-driven task (same GET-then-POST pattern). Left out of this PR because
   it requires real tracker accounts to test end-to-end.

## Installation

Wired into `playbooks/site.yml` (Phase 8c, after the `*arr` roles) against the
`download_vpn_group` coordinator host (it can reach every media app over the
LAN). config.xml edits are delegated to each app's host. Install the collection
dependencies once:

```sh
ansible-galaxy collection install -r requirements.yml
```

Prerequisites: the `download_vpn`, `sonarr`, and `radarr` roles have run (apps
installed), and SOPS holds `SONARR_API_KEY` / `RADARR_API_KEY` /
`PROWLARR_API_KEY` (generate each with `openssl rand -hex 16`).

## Usage

```sh
sops exec-env secrets.enc.yaml 'doppler run -- \
  ansible-playbook playbooks/site.yml --tags servarr_wiring'
```

The role asserts `SONARR_API_KEY` / `RADARR_API_KEY` / `PROWLARR_API_KEY` are
all set and fails fast with a pointer to SOPS if any are missing.

## How it's built

- `defaults/main.yml` — API keys (SOPS env), per-app data dirs / hosts / ports
  (ports from Terraform constants), wiring parameters, `servarr_wiring_manage_services`
  toggle (false in Molecule).
- `tasks/main.yml` — assertion → `api_keys.yml` → `prowlarr_apps.yml` →
  `download_client.yml` (once per PVR).
- `tasks/api_keys.yml` — `community.general.xml` sets `<ApiKey>` per app
  (delegated), restart-on-change, wait-for-API.
- `tasks/prowlarr_apps.yml` — schema-driven Prowlarr Application add.
- `tasks/download_client.yml` — per PVR: root folder, schema-driven qBittorrent
  client, and completed-download handling.

## Secrets

| Variable                     | Purpose                                             | Source                  |
| ---------------------------- | --------------------------------------------------- | ----------------------- |
| `SONARR_API_KEY`             | Deterministic Sonarr API key (32 hex)               | SOPS `secrets.enc.yaml` |
| `RADARR_API_KEY`             | Deterministic Radarr API key (32 hex)               | SOPS `secrets.enc.yaml` |
| `PROWLARR_API_KEY`           | Deterministic Prowlarr API key (32 hex)             | SOPS `secrets.enc.yaml` |
| `QBITTORRENT_ADMIN_PASSWORD` | qBittorrent WebUI auth (shared with `download_vpn`) | SOPS `secrets.enc.yaml` |

None are ever committed to git.
