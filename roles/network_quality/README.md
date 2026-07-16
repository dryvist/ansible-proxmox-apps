# network_quality

Deploys active **network-quality probing** as a Docker-in-LXC compose stack —
co-located on the monitoring (`prometheus`) LXC alongside `prometheus_stack`:

- **[smokeping_prober](https://github.com/SuperQ/smokeping_prober)** (`:9374`,
  `NET_RAW`): continuous ~1 packet/s ICMP stream to each target, exposing per-host
  **latency-distribution histograms** + loss. Prometheus scrapes it. This is the
  loss/latency-**distribution** leg that blackbox's binary `probe_success` lacks.

`irtt` (jitter/MOS) is **deferred** — see below. The role is named `network_quality`
(not `smokeping`) so the jitter/atlas legs can be added later without a rename.

See `tofu-proxmox/docs/SMOKEPING.md` for the measurement design.

## Networking

Both services run on `network_mode: host`: smokeping_prober needs it so ICMP
egresses the LXC's uplink (the per-WAN source-IP policy route governs the path) and
`NET_RAW` lets it open raw sockets. They are **not** on an internal bridge — that
would break ICMP source-routing (same rationale as `prometheus_stack`).

## daemon.json ownership

This role does **not** write `/etc/docker/daemon.json`. The registry-mirror play in
`playbooks/site.yml` is the single owner of that file on docker LXCs.

## Wiring smokeping into Prometheus

smokeping_prober is scraped with a single static job, defined in
`inventory/group_vars/prometheus_group.yml` as
`prometheus_stack_extra_scrape_configs`. `prometheus.yml.j2` (in `prometheus_stack`)
appends that block and the `Reload prometheus config` handler hot-reloads — no
Prometheus restart.

The job lives in `group_vars` (not this role's defaults) because the
`prometheus_stack` play does not load this role's defaults — the scrape config must
be visible to whichever play renders `prometheus.yml`. Its port comes from the same
tofu `smokeping_prober` constant this role uses, so the two stay in sync.

## irtt is deferred

`irtt` (RFC-3393 jitter / MOS) is **not** included. There is no official or
maintained irtt container image — the upstream repo ships no Dockerfile and only
low-signal community forks exist on Docker Hub — and real jitter/MOS needs an `irtt
client` run against a *remote* irtt server anyway, not just a local responder.
Revisit by building irtt from source (small Go binary) or vetting a community image;
tracked as a follow-up. The role name leaves room to add it later.

## Targets / privacy

Probe targets default to **generic** values only, defined once as
`network_quality_modem_ip` (`192.168.100.1`) + `network_quality_anycast_targets`
(`1.1.1.1` / `8.8.8.8`); `network_quality_smokeping_targets` derives from them. Real
ISP hop IPs are home-specific — override those vars (or the whole
`network_quality_smokeping_targets` list) via a **private** inventory; never commit
them to this public repo.

## Variables

See `defaults/main.yml`: `network_quality_smokeping_image` /
`network_quality_irtt_image` (pinned, Renovate-tracked), `*_port` (tofu
`smokeping_prober` / `irtt` constants, defaults `9374` / `2112`),
`network_quality_smokeping_targets`, `network_quality_smokeping_interval` (`1s`),
and `network_quality_smokeping_scrape_config` (the Prometheus job snippet).

## Installation

This role ships with the repo; no separate install step. Its only collection
dependency, `community.docker`, is pinned in the repo-root `requirements.yml`.
Hosts are selected from the terraform inventory: the metrics LXC (`prometheus`
hostname / `monitoring` tag) is grouped by `inventory/load_tofu.yml`, and the
`network_quality` play in `playbooks/site.yml` runs this role against it.

## Usage

Scoped run (never the full `site.yml`):

```bash
ansible-playbook playbooks/site.yml --tags smokeping
```

## Handlers

- `Restart network_quality stack` — recreates the compose stack against the
  rendered config.
