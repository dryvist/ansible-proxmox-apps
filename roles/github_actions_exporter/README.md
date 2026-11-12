# github_actions_exporter

Deploy [github-actions-runner-exporter](https://github.com/drumandbytes/github-actions-runner-exporter)
beside `prometheus_stack` as a pinned Docker container. It provides job queue
histograms labelled by workflow, job, runner and runner label, plus online and
busy gauges for registered runners. Prometheus scrapes these metrics and sends
them through the existing VictoriaMetrics remote-write path.

## Credentials

The role reads `github_actions_exporter_token` from the existing
`bao_apps_secrets` map. For local or gated runs, it also accepts the
`GITHUB_ACTIONS_EXPORTER_TOKEN` environment variable. The role stores the
rendered environment file as root-only (`0600`) and skips deployment while the
token is absent.

The organization value comes from inventory through
`github_actions_exporter_org`; it is not stored in role defaults or templates.
For organization-wide coverage, a fine-grained token needs access to all
repositories, with read-only Metadata, Actions, Pull requests and Dependabot
alerts permissions. It also needs the organization's read permission for
self-hosted runner status. The exact fine-grained organization permission is
not available on every GitHub plan; follow the upstream token documentation
for the supported account type.

## Deployment

The role is included in the site playbook for `prometheus_group`, after the
Prometheus service is configured. Once the token is provisioned in OpenBao,
converge that group with the `monitoring` tag so Prometheus renders the scrape
job and the exporter starts. Later exporter-only updates can use the
`github_actions_exporter` tag.

Job queue histograms are observed for completed jobs after the exporter starts;
earlier jobs are not backfilled by the upstream exporter.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `github_actions_exporter_image` | `ghcr.io/drumandbytes/github-actions-runner-exporter:v1.4.1` | Pinned upstream image. |
| `github_actions_exporter_container_name` | `github-actions-runner-exporter` | Container name. |
| `github_actions_exporter_port` | `9222` | Container and host metrics port. |
| `github_actions_exporter_data_dir` | `/opt/github-actions-runner-exporter` | Compose project and protected environment file. |
| `github_actions_exporter_org` | Inventory supplied | GitHub organization to monitor. |
| `github_actions_exporter_token` | OpenBao field or environment fallback | Read-only GitHub API token. |
