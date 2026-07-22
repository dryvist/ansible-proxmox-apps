# servarr_wiring

Idempotent **Servarr API self-wiring**: a single converge auto-configures the
Prowlarr ↔ Sonarr/Radarr pipeline so the media stack is "hands-off" after
deploy. No clicking through web UIs.

This role runs **after** the apps are installed (`download_vpn` provides
Prowlarr + qBittorrent; `sonarr` / `radarr` provide the PVRs) and wires them
together over the LAN.

## Scope (what this role owns)

This role owns the **VPN-reachable cross-app API wiring** — the parts that must
run from inside the `download_vpn` coordinator (it sits behind the Proton VPN
and can still reach the other media LXCs on the LAN). Root folders and download
clients are managed upstream; quality selection uses the applications' native
profiles:

| Config | Owner |
| --- | --- |
| Root folders + qBittorrent download clients | devopsarr **`servarr-config`** tofu module (`tofu-proxmox`) |
| Normal request quality | stock `HD - 720p/1080p` profile in Sonarr/Radarr |

This role does not POST root folders or download clients. On its first run
after this change, it migrates only items on the retired `WEB-1080p` (Sonarr)
and `HD Bluray + WEB` (Radarr) profiles to the native HD profile, verifies no
items remain on those legacy profiles, then deletes them. Other explicit
profile choices are left untouched.

## What it does (all idempotent — GET-then-POST/PUT)

1. **Deterministic API keys** — sets `<ApiKey>` in each app's `config.xml`
   (Sonarr `/var/lib/sonarr`, Radarr `/var/lib/radarr`, Prowlarr
   `/var/lib/prowlarr`) from the environment, delegated to each app's host. Restarts
   the app and waits for its API only when the key actually changed. Templating
   the key means every cross-app reference is known **before** converge instead
   of being auto-generated.
2. **Public Prowlarr indexers** — adds the indexers in
   `servarr_wiring_prowlarr_indexers` (default: public, non-Cloudflare trackers)
   so Prowlarr has something to search. Without an indexer the Application sync
   below pushes nothing and the PVRs can never find a release. Schema-driven:
   GET `/api/v1/indexer/schema`, overlay `enable` + `appProfileId`, POST if
   absent. Cloudflare-gated indexers (needing FlareSolverr) are out of scope.
3. **Prowlarr → Sonarr/Radarr Applications** — adds each as a Prowlarr
   Application with sync level `fullSync`, so Prowlarr pushes its indexers to
   both. Schema-driven: the role GETs `/api/v1/applications/schema`, overrides
   only `prowlarrUrl` / `baseUrl` / `apiKey`, and POSTs if absent.
4. **Media management** — sets `copyUsingHardlinks` (zero-copy imports off the
   single `/data` dataset), a recycle bin (soft-delete) and a minimum
   free-space floor on each PVR, via GET-then-conditional-PUT.

## Why `ansible.builtin.uri` and not a community role / Buildarr

A search-first pass (logged in the PR) found the community Servarr Ansible
roles (`tinyoverflow`, `coaxial`, `Amixp`, `sleepy_nols`) are **install-only**
— none do cross-app API wiring. For the LAN-reachable structural config (root
folders, download clients, quality profiles) the stack now uses declarative
tool — the `servarr-config` tofu module — but the **VPN-locked** Prowlarr
wiring this role still owns has to run from inside the
`download_vpn` coordinator, where those LAN/CI-reachable tools cannot reach. So
this role keeps the repo's vetted house pattern — `ansible.builtin.uri`
GET-then-POST, the same one the `download_vpn` role uses for qBittorrent.

## Indexers (public seeded here; private = manual / SOPS step)

Step 2 seeds the **public** trackers in `servarr_wiring_prowlarr_indexers`.
Private trackers need per-user credentials (cookies, passkeys, API tokens) that
are account-scoped and cannot be derived from infrastructure — add those in the
Prowlarr UI (Indexers → Add Indexer); Prowlarr's `fullSync` Application then
pushes them to Sonarr/Radarr automatically.

## Installation

Wired into `playbooks/site.yml` (Phase 8c, after the `*arr` roles) against the
`download_vpn_group` coordinator host (it can reach every media app over the
LAN). config.xml edits are delegated to each app's host. Install the collection
dependencies once:

```sh
ansible-galaxy collection install -r requirements.yml
```

Prerequisites: the `download_vpn`, `sonarr`, and `radarr` roles have run (apps
installed), and `SONARR_API_KEY` / `RADARR_API_KEY` / `PROWLARR_API_KEY` are
set in the environment (generate each with `openssl rand -hex 16`).

## Usage

```sh
sops exec-env secrets.enc.yaml 'doppler run -- ./scripts/fetch-openbao-secrets.sh media -- \
  ansible-playbook playbooks/site.yml --tags servarr_wiring'
```

The role asserts `SONARR_API_KEY` / `RADARR_API_KEY` / `PROWLARR_API_KEY` are
all set and fails fast if any are missing.

## How it's built

- `defaults/main.yml` — API keys (environment), per-app data dirs / hosts / ports
  (ports from OpenTofu constants), wiring parameters, `servarr_wiring_manage_services`
  toggle (false in Molecule).
- `tasks/main.yml` — assertion → `api_keys.yml` → `prowlarr_indexers.yml` →
  `prowlarr_apps.yml` → `media_management.yml`.
- `tasks/api_keys.yml` — `community.general.xml` sets `<ApiKey>` per app
  (delegated), restart-on-change, wait-for-API.
- `tasks/prowlarr_indexers.yml` — schema-driven public-indexer add.
- `tasks/prowlarr_apps.yml` — schema-driven Prowlarr Application add.
- `tasks/media_management.yml` — per PVR: hardlinks, recycle bin, min free space.

## Secrets

| Variable           | Purpose                                 |
| ------------------ | --------------------------------------- |
| `SONARR_API_KEY`   | Deterministic Sonarr API key (32 hex)   |
| `RADARR_API_KEY`   | Deterministic Radarr API key (32 hex)   |
| `PROWLARR_API_KEY` | Deterministic Prowlarr API key (32 hex) |

Supplied as plain environment variables — however you manage that (a local
`.env` you source, your own secrets manager, CI secrets, ...). None are ever
committed to git.
