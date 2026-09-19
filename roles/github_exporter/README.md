# github_exporter

Installs [promhippie/github_exporter](https://github.com/promhippie/github_exporter)
as a pinned-version native systemd service, co-located on the `prometheus_group`
LXC and scraped locally (same shape as `roles/prometheus_pve_exporter` and
`roles/node_exporter`).

## What it ships today: runner online/busy only

This exporter has three collectors relevant to CI observability, but only
one of them is enabled here:

| Collector | Data source | Status |
| --- | --- | --- |
| `runners` | Live poll: `GET /orgs/{org}/actions/runners` | **Enabled** |
| `workflow_runs` | The exporter's own local database | Disabled — see below |
| `workflow_jobs` | The exporter's own local database | Disabled — see below |

`workflow_runs`/`workflow_jobs` never call the GitHub API themselves — their
`Collect()` reads only from a local database populated by the exporter's
built-in `/github` webhook receiver. This estate has no WAN-facing ingress
(no port-forward, tunnel, or public DNS record reaches any internal host),
so GitHub cannot deliver webhook events to it. Enabling these two collectors
as shipped would produce two permanently-empty metric families, not the
queue-time/duration data this exporter usually provides — a known,
tracked gap, not something a wider GitHub App permission fixes.

The `runners` collector needs no webhook: it polls the GitHub API directly,
using the `github-exporter` OpenBao tier (`organization_self_hosted_runners:
read`, `roles/openbao` `03-github-engine.yml`).

## What it does

1. Downloads and checksum-verifies the pinned `.deb` release, which ships
   its own systemd unit (`github-exporter.service`), system user
   (`github-exporter`), and state directory (`/var/lib/github-exporter`).
2. Templates `/etc/default/github-exporter` with the organization, enabled
   collectors, and database DSN — everything except the credential.
3. Installs the OpenBao client and runs a per-host `bao agent`
   (`openbao-github-exporter-agent.service`) that authenticates once via
   AppRole and renders a currently-valid GitHub App installation token to
   `/etc/sysconfig/github-exporter` — the package's unit already reads this
   path as a second, optional `EnvironmentFile=`. The agent restarts
   `github-exporter` on every render (`command =` in its template block),
   including the hourly re-mint an installation token needs; Ansible never
   renders the token itself, because converges run on demand, not on a
   schedule short enough to catch an hourly expiry.

Re-runs are no-ops; bumping `github_exporter_version` (plus its checksums)
rolls the deployment forward on the next converge.

## Installation

No collection dependency: every task uses `ansible.builtin` modules. Consumed
as an ordinary role dependency from `playbooks/site/02-dns-and-pipeline.yml`
against `prometheus_group`; nothing to install separately.

## Usage

Runs with the rest of `site.yml`, or target just this role by tag:

```bash
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --limit prometheus_group,localhost --tags github_exporter
```

### Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `github_exporter_version` | `19.0.0` | Pinned upstream release. |
| `github_exporter_checksum` | pinned per-arch sha256 | `sha256:<hex>` pin for the `.deb`. |
| `github_exporter_web_address` | `127.0.0.1:9504` | Bind address (local-only; scraped via `prometheus_stack_extra_scrape_configs`). |
| `github_exporter_org` | `""` | Organization to poll. Set in `inventory/group_vars/prometheus_group.yml`. |
| `github_exporter_collector_runners` | `true` | Org-level runner online/busy gauges. |
| `github_exporter_collector_workflow_runs` / `_workflow_jobs` | `false` | Off — see "What it ships today" above. |
| `github_exporter_database_dsn` | sqlite path under `/var/lib/github-exporter` | Unused while the two collectors above are off. |
| `github_exporter_token_path` | `github/token/exporter-dryvist` | OpenBao permission-set path the agent mints from. |

## Verification

```bash
systemctl is-active github-exporter openbao-github-exporter-agent
curl -s http://127.0.0.1:9504/metrics | grep github_runner_org
```

## Contributing

Changes go through the repo's standard flow: edit in a worktree, pass
`ansible-lint` and the `tests/template_render` fixture, open a PR. Bump
`github_exporter_version` and both `github_exporter_checksum` entries
together.

## License

Apache-2.0, matching the repository (github_exporter itself is Apache-2.0).
