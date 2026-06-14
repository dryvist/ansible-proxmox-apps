# blackbox_exporter

Deploys the [Prometheus blackbox exporter](https://github.com/prometheus/blackbox_exporter)
as a Docker-in-LXC stack for **active WAN/ISP reachability and response-time
probing**: ICMP latency/loss to the cable modem, the ISP hops, and public anycast
targets; TCP/HTTP(S)/TLS reachability + latency; and DNS RTT.

This is the **system-of-record for "is the link up and how does it feel"** in the
Prometheus-native monitoring design — see `terraform-proxmox/docs/SMOKEPING.md`.
It is the path to proving ISP-side degradation **without** needing the cable
modem to expose SNMP/HTTP (many Comcast modems answer only ICMP).

## How it works

The exporter exposes **modules** (how to probe), and Prometheus supplies the
**target** per scrape via the multi-target pattern:

```text
GET http://<this-host>:9115/probe?target=192.168.100.1&module=icmp
```

So the **targets are not configured here** — they live in the Prometheus scrape
config (the `prometheus` role). This role only defines the modules:

| Module | Probes |
| --- | --- |
| `icmp` | latency/loss to the modem + ISP hops + public anycast |
| `tcp_connect` | bare TCP reachability + connect latency |
| `http_2xx` | HTTP response + latency |
| `http_2xx_tls` | HTTPS response + TLS handshake / cert expiry |
| `dns_udp` | DNS RTT + resolution success |

### Example Prometheus scrape (lives in the `prometheus` role, not here)

```yaml
- job_name: blackbox-icmp
  metrics_path: /probe
  params: { module: [icmp] }
  static_configs:
    - targets: ["192.168.100.1", "1.1.1.1", "8.8.8.8"]   # modem + internet
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - source_labels: [__param_target]
      target_label: instance
    - target_label: __address__
      replacement: "<blackbox-host>:9115"
```

`probe_success`, `probe_duration_seconds`, `probe_icmp_duration_seconds`, and
`probe_http_status_code` then carry the per-target signal for Grafana / alerts.

## Why host networking + NET_RAW

ICMP probes must egress the LXC's uplink so the per-WAN source-IP policy route
(`tofu-unifi`) governs which WAN they traverse, and the icmp prober needs
`NET_RAW` to open raw sockets. Molecule/Docker-in-Docker overrides
`blackbox_exporter_network_mode` to `bridge`.

## Variables

See `defaults/main.yml`. Key ones: `blackbox_exporter_image` (pinned),
`blackbox_exporter_port` (from the tofu `blackbox_exporter` constant, default
`9115`), `blackbox_exporter_modules` (the module set above).

## Installation

This role ships with the repo; no separate install step. Its only collection
dependency, `community.docker`, is pinned in the repo-root `requirements.yml`
(installed by the bootstrap playbook). Hosts are selected from the terraform
inventory: the monitoring vantage LXC (the `smokeping`/`netq-probe-*` guests,
`monitoring` tag) is grouped by `inventory/load_tofu.yml`, and the monitoring
play in `playbooks/site.yml` runs this role against it.

## Usage

Run via the standard site playbook (tags `blackbox`, `monitoring`):

```bash
ansible-playbook playbooks/site.yml --tags blackbox
```

Or include the role directly against the monitoring vantage group:

```yaml
- name: Configure blackbox exporter
  hosts: monitoring_group
  become: true
  roles:
    - role: blackbox_exporter
```

## Handlers

- `Restart blackbox_exporter stack` — recreates the compose stack against the
  rendered config (`recreate: always`).

## Privacy

No homelab IPs, ISP names, or topology live in this role — probe targets are
supplied by Prometheus from inventory/constants. Keep ISP-specific values and
incident data out of this public repo.
