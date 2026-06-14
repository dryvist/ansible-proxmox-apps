# configarr

Declarative [TRaSH-Guides](https://trash-guides.info/) quality profiles and
custom formats for Sonarr/Radarr, applied by the official
[Configarr](https://configarr.de) container. This is the "adopt, don't build"
replacement for hand-maintained quality config: the community keeps the formats
current; this role just points Configarr at the live apps.

## Boundary

- **Configarr (this role)** owns quality profiles + custom formats.
- **devopsarr `servarr-config` (tofu)** owns root folders + download clients.
- No overlap — and Prowlarr stays with `servarr_wiring` (behind the VPN).

## How it runs

A one-shot container on **docker-host** (`hosts: docker_vms[0]` — the first
docker host is enough), where it can reach the *arr LAN and the internet (for
templates) directly — no VPN dependency. Configarr is idempotent: it writes only
what differs, so a re-run on an in-sync stack is a no-op, making it safe on every
converge.

Endpoints resolve from the OpenTofu inventory (`reserved_ip` → `ip` →
discovered `container_ip`), never a hardcoded IP. API keys come from SOPS
(`SONARR_API_KEY` / `RADARR_API_KEY`) under `sops exec-env` — the same
deterministic keys `servarr_wiring` uses. The rendered `config.yml` is
secret-free (URLs + keys live in `secrets.yml`, mode 0600, via Configarr's
`!secret` tag).

## Quality target

720p minimum, 1080p maximum (Bluray + WEB); per-item higher quality is left to
Sonarr/Radarr's native per-series / per-movie profile selection. The template
includes are variables (`configarr_sonarr_templates` /
`configarr_radarr_templates`) — tune them in inventory without editing the
role. Radarr's "HD Bluray + WEB" profile matches the 720p/1080p intent
directly; Sonarr's official TRaSH profiles are WEB-tier-oriented (WEB-1080p is
the 1080p cap), so adjust the allowed qualities there if you want 720p Bluray
on the TV side.

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `configarr_manage` | `true` | master on/off |
| `configarr_image_tag` | `latest` | pin for a frozen version |
| `configarr_sonarr_templates` | WEB-1080p set | Recyclarr/TRaSH includes |
| `configarr_radarr_templates` | HD Bluray+WEB set | Recyclarr/TRaSH includes |

## Installation

No standalone install — the role is part of `playbooks/site.yml` and ships with
the repo. It needs the `community.docker` collection (already pinned in
`requirements.yml`) and a Docker engine on the target (docker-host already has
one). `SONARR_API_KEY` / `RADARR_API_KEY` must be present in the SOPS env.

## Usage

Runs automatically in its `site.yml` play (`hosts: docker_vms[0]`). To apply
just this role against the live stack:

```bash
sops exec-env secrets.enc.yaml \
  'ansible-playbook playbooks/site.yml --tags configarr --limit docker_vms'
```

Disable it without removing the play by setting `configarr_manage: false`. Tune
the enforced profiles via `configarr_sonarr_templates` /
`configarr_radarr_templates` in inventory.
