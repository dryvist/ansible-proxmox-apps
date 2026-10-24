# prometheus_stack

Deploys [Prometheus](https://prometheus.io/) **and** the
[blackbox_exporter](https://github.com/prometheus/blackbox_exporter) as a **single
Docker-in-LXC compose stack** — one project, two services. This is the **system of
record** for the Prometheus-native network-quality monitoring stack (see
`tofu-proxmox/docs/SMOKEPING.md`). Prometheus scrapes the co-located exporter
via the multi-target `/probe` pattern, producing WAN/ISP loss, latency, and
reachability metrics, and grows `smokeping_prober` / `irtt` / `snmp_exporter` jobs
as those roles land.

This role supersedes the former separate `prometheus` + `blackbox_exporter` roles:
both ran on the same host and each carried an identical ~90-line Docker bootstrap.
Merging removes the duplicate bootstrap and lets the two containers share one
compose project.

## What it scrapes

| Job | Source | Signal |
| --- | --- | --- |
| `prometheus` | self | scrape health |
| `blackbox_icmp` | blackbox `/probe?module=icmp` | loss + RTT to the modem (`192.168.100.1`) + internet |
| `blackbox_http_2xx_tls` | blackbox | HTTPS response + TLS health |
| `blackbox_http_401_tls` | blackbox | Expected HTTP 401 + TLS health for protected services |
| `blackbox_dns_udp` | blackbox | DNS RTT + resolution |
| `phoenix_postgres` | Phoenix-tagged guests' PostgreSQL exporter | PostgreSQL exporter metrics |

`probe_success` + `probe_duration_seconds` per target carry the ISP-degradation
signal — this is the evidence path now that the modem exposes no DOCSIS data.

The `llm_gpu_engine` job scrapes the active engine's native `/metrics` endpoint
and labels each target with its inventory guest name. `dcgm_exporter` remains a
separate job for GPU hardware metrics.

Prometheus also loads every `rules/*.yml` file from the pinned
[`dryvist/prometheus-homelab-rules`](https://github.com/dryvist/prometheus-homelab-rules)
checkout. The role validates each file with `promtool check rules` in the
Prometheus image before a rules update can trigger the lifecycle reload. The
checkout commit is `prometheus_stack_rules_version` in `defaults/main.yml`.

## Networking

Both services run on `network_mode: host`. blackbox needs it so ICMP probes egress
the LXC uplink (the per-WAN source-IP policy route governs the path) and `NET_RAW`
lets the icmp prober open raw sockets; Prometheus needs it to reach exporters
across VLANs and to scrape blackbox on `127.0.0.1`. They are **not** on an internal
bridge — that would break ICMP source-routing.

## daemon.json ownership

This role does **not** write `/etc/docker/daemon.json`. Its `docker_engine` meta
dependency supplies the shared renderer, which sets the mirror and LXC storage
driver together; the site play reuses it for already-installed Docker hosts.

## Targets / privacy

Probe targets default to **generic** values only and are defined **once** as
`prometheus_stack_modem_ip` (cable-modem diagnostic IP, `192.168.100.1`) and
`prometheus_stack_anycast_targets` (public resolvers, `1.1.1.1` / `8.8.8.8`); the
per-module scrape jobs and the smoke-test target derive from them. Real ISP hop
IPs and ISP-specific targets are home-specific — override those two vars (or the
whole `prometheus_stack_blackbox_jobs` list) via a **private** inventory; never
commit them to this public repo.

## Variables

See `defaults/main.yml`: `prometheus_stack_image` / `prometheus_stack_blackbox_image` (pinned),
`prometheus_stack_port` (tofu `prometheus_web`, default `9090`), `prometheus_stack_blackbox_port`
(tofu `blackbox_exporter`, default `9115`), `prometheus_stack_retention` (`30d`),
`prometheus_stack_blackbox_jobs` (probe modules + targets), `prometheus_stack_blackbox_modules`
(how to probe), `prometheus_stack_blackbox_address` (where Prometheus reaches the exporter;
co-located by default), `prometheus_stack_smoke_target` (post-deploy probe check),
and `prometheus_stack_extra_scrape_configs` (raw YAML appended for later exporters).
`prometheus_stack_remote_write_receiver_enabled` opts into the internal
Prometheus remote_write endpoint for declared metric sources.

## Migration

On first run the role tears down the legacy standalone blackbox compose project at
`prometheus_stack_legacy_blackbox_dir` (`/opt/blackbox-exporter`) so its fixed
container name is free for the merged project. The Prometheus TSDB volume is
preserved (same project name / data dir).

## Installation

This role ships with the repo; no separate install step. Its only collection
dependency, `community.docker`, is pinned in the repo-root `requirements.yml`.
Hosts are selected from the terraform inventory: the metrics LXC (`prometheus`
hostname / `monitoring` tag) is grouped by `inventory/load_tofu.yml`, and the
monitoring play in `playbooks/site.yml` runs this role against it.

## Usage

Run via the standard site playbook (scoped — never the full `site.yml`):

```bash
ansible-playbook playbooks/site.yml --tags prometheus
```

Or include the role directly against the metrics host:

```yaml
- name: Configure the prometheus stack
  hosts: prometheus_group
  become: true
  roles:
    - role: prometheus_stack
```

## Handlers

- `Reload Prometheus rules` — posts to the lifecycle API after a validated
  rules checkout change. The rules directory is bind-mounted read-only, so its
  updated contents are visible to the running container.
- `Restart prometheus stack` — recreates the compose stack (TSDB persists in
  the named volume). Every rendered file is bind-mounted as a single file, so
  only a recreate — not the `/-/reload` lifecycle API — actually picks up a
  change (a single-file bind mount does not follow the atomic rename
  `ansible.builtin.template` writes).
