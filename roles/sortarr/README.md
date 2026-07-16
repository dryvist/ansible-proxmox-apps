# sortarr

Runs [Sortarr](https://github.com/Jaredharper1/Sortarr) (a read-only
media-library insights dashboard) as a single Docker container on a
dedicated Docker-in-LXC (`sortarr`), publishes the web UI on the
OpenTofu-derived port (`media_ports.sortarr_web` = 8787), and persists its
config to a host directory.

This role mirrors the `seerr` Docker-in-LXC pattern: install Docker CE +
Compose, `fuse-overlayfs` for ZFS-backed LXC, a Python venv for the
`community.docker` modules, then a one-container Compose project.

Sortarr is **read-only** — it never moves, renames, or deletes media. It
reaches Sonarr, Radarr, and (optionally) Plex over the LAN using their
existing API keys; no `*arr`-side wiring is required (unlike `seerr`, it
registers nothing back into those apps).

## Installation

Wired into `playbooks/site.yml` (Phase 8c, media stack) against any host in
`sortarr_group`. The group is populated by `inventory/load_tofu.yml`
from `containers` tagged `sortarr` in the OpenTofu inventory
(tofu-proxmox `sortarr` LXC), reached over `proxmox_pct_remote`.

Prerequisites:

- The `sortarr` LXC exists (OpenTofu-managed; tags include `container`,
  `media`, `sortarr`; `nesting=true` for Docker).
- Sonarr/Radarr API keys and a Sortarr basic-auth password are available as
  environment variables, e.g. via a local `.env` (however you manage that —
  the secret store this homelab uses is an implementation detail; anything
  that sets the same variables works).

Install the collection dependencies once:

```sh
ansible-galaxy collection install -r requirements.yml
```

## Usage

```sh
# From the repo root, with the secret-store env loaded:
ansible-playbook playbooks/site.yml --tags sortarr
```

The role asserts `SONARR_API_KEY`, `RADARR_API_KEY`, and
`SORTARR_BASIC_AUTH_PASS` are all set before doing any work and fails fast
if any is missing.

## Access

After a successful run on the `sortarr` LXC:

| Service | URL                            | Container |
| ------- | ------------------------------ | --------- |
| Sortarr | `http://<sortarr-host>:8787/`  | `sortarr` |

## Auth mode

Configured as **basic_local_bypass**: a login (`BASIC_AUTH_USER` /
`BASIC_AUTH_PASS`) is required from outside the media VLAN, but bypassed for
clients on `sortarr_local_auth_bypass_cidrs` (the media VLAN itself, and the
Traefik reverse-proxy hop). See upstream's
[`docs/Sortarr.minimal.env.example`](https://github.com/Jaredharper1/Sortarr/blob/master/docs/Sortarr.minimal.env.example)
for the full auth-mode contract.

## Sources (Sonarr / Radarr / Plex)

Hostnames default to the media-stack LXC IPs from inventory; ports come from
OpenTofu constants. Plex is optional — Sortarr works with just Sonarr +
Radarr; the Plex overlay (playback/history) is added only when
`PLEX_TOKEN` is set.

## How it's built

- `defaults/main.yml` — image, ports (from OpenTofu constants), config dir,
  Sonarr/Radarr/Plex source + secret variables, auth-mode variables,
  `sortarr_manage_services` toggle (false in Molecule).
- `templates/docker-compose.yml.j2` — one `sortarr` service, binds
  `<bind_address>:<web_port>:8787`, mounts the host config dir to `/data`.
- `tasks/main.yml` — secrets assertion → Docker install → venv → data dirs
  → persistence guard → compose deploy → port + HTTP health check.

## Secrets

| Variable                  | Purpose                               | Source               |
| ------------------------- | ------------------------------------- | -------------------- |
| `SONARR_API_KEY`          | Sonarr API key (read library/queue)   | environment variable |
| `RADARR_API_KEY`          | Radarr API key (read library/queue)   | environment variable |
| `PLEX_TOKEN`              | Optional Plex account token (overlay) | environment variable |
| `SORTARR_BASIC_AUTH_PASS` | Sortarr's own basic-auth password     | environment variable |

None are ever committed to git. The role's first task asserts the required
ones are set and fails fast if any is missing.
