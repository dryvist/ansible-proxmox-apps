# prometheus

Deploys [Prometheus](https://prometheus.io/) as a Docker-in-LXC stack — the
**system of record** for the Prometheus-native network-quality monitoring stack
(see `terraform-proxmox/docs/SMOKEPING.md`). It scrapes the `blackbox_exporter`
via the multi-target `/probe` pattern, producing the WAN/ISP loss, latency, and
reachability metrics, and grows `smokeping_prober` / `irtt` / `snmp_exporter`
jobs as those roles land.

## What it scrapes

| Job | Source | Signal |
| --- | --- | --- |
| `prometheus` | self | scrape health |
| `blackbox_icmp` | blackbox `/probe?module=icmp` | loss + RTT to the modem (`192.168.100.1`) + internet |
| `blackbox_http_2xx_tls` | blackbox | HTTPS response + TLS health |
| `blackbox_dns_udp` | blackbox | DNS RTT + resolution |

`probe_success` + `probe_duration_seconds` per target carry the ISP-degradation
signal — this is the evidence path now that the modem exposes no DOCSIS data.

## Targets / privacy

Probe targets default to **generic** values only (the cable-modem diagnostic IP
`192.168.100.1` and public anycast `1.1.1.1` / `8.8.8.8`). Real ISP hop IPs and
ISP-specific targets are home-specific — supply them via a **private** inventory
override of `prometheus_blackbox_jobs`; never commit them to this public repo.

## Variables

See `defaults/main.yml`: `prometheus_image` (pinned), `prometheus_port` (tofu
`prometheus_web`, default `9090`), `prometheus_retention` (`30d`),
`prometheus_blackbox_address` (host:port of the exporter; co-located by default),
`prometheus_blackbox_jobs` (probe modules + targets), and
`prometheus_extra_scrape_configs` (raw YAML appended for later exporters).

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
- name: Configure prometheus
  hosts: prometheus_group
  become: true
  roles:
    - role: prometheus
```

## Handlers

- `Reload prometheus config` — POST `/-/reload` (config-only change; no restart,
  no scrape gap).
- `Restart prometheus stack` — recreates the compose stack (TSDB persists in the
  named volume).
