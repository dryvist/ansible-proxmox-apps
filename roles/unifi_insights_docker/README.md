# unifi_insights_docker

Deploys UniFi Insights (UniFi-Insights-Plus) as one Docker container with
Docker Compose, on the `unifi-insights` VM. The container serves the web UI and
API on port 8000 and receives UniFi gateway syslog on UDP 514.

## Installation

The role is applied by the `Deploy UniFi Insights` play in
`playbooks/site/03-notifications-and-core-apps.yml`. It targets the
`unifi_insights` inventory group, which the loader builds from the
`unifi-insights` tag on a VM in the tofu-proxmox desired state. The role pulls
Docker from the `docker_engine` dependency.

## Usage

Converge the role alone with the scoped form from `docs/agents/commands-and-testing.md`:

```bash
scripts/run-ansible.sh playbooks/site.yml --tags unifi_insights --limit unifi_insights,localhost
```

Check the container on the VM after a converge:

```bash
docker compose -f /opt/unifi-insights/docker-compose.yml ps
```

## Host ports

Published by tofu-proxmox in `service_ports`:

| Constant | Value | Container port |
| --- | --- | --- |
| `unifi_insights_web` | 8001 | 8000 (web and API) |
| `unifi_insights_syslog` | 514/udp | 514/udp (syslog) |

## Secrets

Read from the apps OpenBao domain through `bao_apps_secrets`, in
`inventory/group_vars/unifi_insights.yml`. A missing value fails the converge.

| Prefetch key | Used as | Required |
| --- | --- | --- |
| `unifi_insights_postgres_password` | `POSTGRES_PASSWORD`, which also keys the embedded database | yes |
| `unifi_insights_secret_key` | `SECRET_KEY` | yes |
| `UNIFI_API` | `UNIFI_HOST`, the controller address the unpoller role reads | no |
| `unifi_insights_unifi_api_key` | `UNIFI_API_KEY` | no |

The controller variables (`UNIFI_HOST`, `UNIFI_SITE`, `UNIFI_VERIFY_SSL`,
`UNIFI_API_KEY`) are rendered only when `unifi_insights_unifi_api_key` is
set. Without it the container runs syslog-only.

Changing `unifi_insights_postgres_password` after first start breaks the
existing database volume.

## Container settings

Set in `defaults/main.yml`. `AUTH_ENABLED` stays `true`. MaxMind and
AbuseIPDB keys are not configured.

## Data

Compose state lives in `/opt/unifi-insights`. The embedded PostgreSQL data is
a named volume, `pgdata`. GeoIP databases mount from `/opt/unifi-insights/maxmind`.
