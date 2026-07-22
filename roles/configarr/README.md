# configarr

Declarative [TRaSH-Guides](https://trash-guides.info/) configuration for
Sonarr/Radarr, applied by the official
[Configarr](https://configarr.de) container. This is the "adopt, don't build"
replacement for hand-maintained quality config: the community keeps the formats
current; this role just points Configarr at the live apps.

## Boundary

- **Configarr (this role)** owns reusable quality definitions and future
  non-client-specific policy.
- **devopsarr `servarr-config` (tofu)** owns root folders + download clients.
- No overlap — and Prowlarr stays with `servarr_wiring` (behind the VPN).

## How it runs

A one-shot container on **docker-host** (`hosts: docker_vms[0]` — the first
docker host is enough), where it can reach the *arr LAN and the internet (for
templates) directly — no VPN dependency. Configarr is idempotent: it writes only
what differs, so a re-run on an in-sync stack is a no-op, making it safe on every
converge.

Endpoints resolve from the OpenTofu inventory (`reserved_ip` → `ip` →
discovered `container_ip`), never a hardcoded IP. API keys
(`SONARR_API_KEY` / `RADARR_API_KEY`) come in as plain environment
variables — the same deterministic keys `servarr_wiring` uses. The rendered
`config.yml` is
secret-free (URLs + keys live in `secrets.yml`, mode 0600, via Configarr's
`!secret` tag).

## Quality policy

Normal Seerr requests use Sonarr/Radarr's stock `HD - 720p/1080p` profile: no
SD and no resolution above 1080p. A higher profile remains an explicit per-item
choice. The retired `WEB-1080p` and `HD Bluray + WEB` profiles, their audio
scoring, and their Apple-TV-specific custom-format policy are intentionally not
rendered again. The template include lists remain variables
(`configarr_sonarr_templates` / `configarr_radarr_templates`) so Configarr can
grow with new general-purpose policy without recreating client-specific rules.

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `configarr_manage` | `true` | master on/off |
| `configarr_image_tag` | `latest` | pin for a frozen version |
| `configarr_sonarr_templates` | quality definition | Recyclarr/TRaSH includes |
| `configarr_radarr_templates` | quality definition | Recyclarr/TRaSH includes |

## Installation

No standalone install — the role is part of `playbooks/site.yml` and ships with
the repo. It needs the `community.docker` collection (already pinned in
`requirements.yml`) and a Docker engine on the target (docker-host already has
one). `SONARR_API_KEY` / `RADARR_API_KEY` must be present in the environment.

## Usage

Runs automatically in its `site.yml` play (`hosts: docker_vms[0]`). To apply
just this role against the live stack:

```bash
sops exec-env secrets.enc.yaml \
  './scripts/fetch-openbao-secrets.sh media -- ansible-playbook playbooks/site.yml --tags configarr --limit docker_vms'
```

Disable it without removing the play by setting `configarr_manage: false`. Add
or tune reviewed general-purpose policy through `configarr_sonarr_templates` /
`configarr_radarr_templates` in inventory.
