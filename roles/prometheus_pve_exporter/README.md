# prometheus_pve_exporter

Deploy [prometheus-pve-exporter](https://github.com/prometheus-pve/prometheus-pve-exporter)
as a Docker container, co-located with `prometheus_stack` on the monitoring
guest. It is a **multi-target** exporter for the PVE cluster API: Prometheus
passes the PVE endpoint to query via a `?target=` query parameter at scrape
time (the same pattern `prometheus_stack`'s blackbox_exporter job already
uses) — this role's own container config carries no PVE node address at all,
so it never needs a literal IP/hostname.

## What It Does

1. Skips entirely (with a visible message) while no PVE API token is
   provisioned — see "Provisioning the PVE API token" below.
2. Once a token exists, renders `pve.yml` (the exporter's PVE credential
   config) and a single-container `docker-compose.yml`, deploys via
   `docker_compose_v2`, and verifies the container answers.

## Installation

No collection dependency beyond `community.docker` (already a repo
requirement for every `*_docker` role). Consumed as an ordinary role
dependency from `playbooks/site.yml`; nothing to install separately.

## Provisioning the PVE API token

Out of scope for this role (no live converge, no credential creation here).
An operator creates a **read-only, audit-scoped** PVE API token — never the
Terraform provider's write-capable credential — and promotes it into OpenBao:

```bash
pveum user token add exporter@pve pve-exporter --privsep 1
# grant PVEAuditor (or narrower) on the token, not the user
```

The token identity (`user@realm!tokenname`) and secret then get promoted to
`secret/apps/pve-exporter` as `PVE_EXPORTER_TOKEN_ID` / `PVE_EXPORTER_TOKEN_SECRET`
(see `roles/openbao` `openbao_promoted_app_secrets.pve-exporter` and
`roles/openbao_secrets` `openbao_secrets_domains` → `apps` → `apps/pve-exporter`),
the same promotion mechanism as every other externally-created credential in
this repo. Until that exists, `bao_apps_secrets.pve_exporter_token_id`/
`_secret` are empty and this role no-ops.

## Where It Runs

Wired into `playbooks/site.yml` against `prometheus_group` (the same guest as
`prometheus_stack`), after `network_quality`. Scraping it from Prometheus
(the job, targets, and relabeling) is Wave 3a's responsibility, not this
role's — this role only makes sure the exporter software runs and answers.

## Usage

```bash
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --limit prometheus_group,localhost --tags prometheus_pve_exporter
```

### Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `prometheus_pve_exporter_image` | `prompve/prometheus-pve-exporter:3.5.5` | Pinned upstream image. |
| `prometheus_pve_exporter_container_name` | `pve-exporter` | Container name. |
| `prometheus_pve_exporter_port` | `9221` | Host port the exporter's multi-target endpoint is published on. |
| `prometheus_pve_exporter_data_dir` | `/opt/prometheus-pve-exporter` | Compose project directory. |
| `prometheus_pve_exporter_token_id` | `bao_apps_secrets.pve_exporter_token_id` (env fallback) | Full PVE token identity (`user@realm!tokenname`). |
| `prometheus_pve_exporter_token_secret` | `bao_apps_secrets.pve_exporter_token_secret` (env fallback) | PVE token secret value. |
| `prometheus_pve_exporter_verify_ssl` | `false` | PVE's self-signed cert is not distributed to this container by this role. |

## Verification

```bash
curl -s 'http://<guest-mgmt-ip>:9221/pve?target=<pve-node-fqdn>' | head
```

## License

Apache-2.0, matching the repository (prometheus-pve-exporter itself is
MIT-licensed upstream).
