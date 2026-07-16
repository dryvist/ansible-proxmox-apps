# netmon

Per-WAN network-diagnosis prober. Deploys a Telegraf agent (Docker-in-LXC) on
each `netmon` prober that runs native active probes plus per-uplink device
telemetry, then ships the results Splunk-HEC → Cribl Edge → Splunk `netmon`
index.

## Purpose

A separate prober per uplink (`netmon-cable`, `netmon-sat`, …) lets you tell
*which* WAN is degrading, when, and how. Each prober runs one Telegraf agent:

- `inputs.ping` / `inputs.dns_query` / `inputs.http_response` — latency, loss,
  jitter, DNS RTT and HTTPS response time on every uplink kind.
- `inputs.snmp` — DOCSIS modem telemetry (downstream power, SNR/MER, codeword
  errors, T3/T4 timeouts) on `cable` probers.
- `inputs.prometheus` — scrapes a Starlink dish gRPC exporter (sidecar) on
  `satellite` probers, and optionally a decoupled speedtest-exporter.
- `outputs.http` — Splunk-HEC format to Cribl Edge.

All collection is native Telegraf inputs + off-the-shelf exporters — no scripts.

## Uplink selection

`netmon_uplink_kind` (`cable` | `satellite` | `lte` | `generic`) decides which
device-telemetry inputs run. It defaults from the hostname (`netmon-cable` →
`cable`, `netmon-sat` → `satellite`); override in `host_vars` otherwise.

## Per-WAN routing dependency

A prober reaches *its* link's device (modem/dish, conventionally
`192.168.100.1`) only when its traffic egresses the assigned uplink. The
source-IP policy route per prober is owned by **tofu-unifi** (gated). Until it
applies, a prober measures the default-route uplink only; active probes and the
exporter sidecar still populate.

## Key variables

All in `defaults/main.yml`. Notable:

| Variable | Default | Purpose |
| --- | --- | --- |
| `netmon_uplink_kind` | hostname-derived | Which device telemetry runs |
| `netmon_docsis_modem_host` | `192.168.100.1` | Cable modem SNMP agent |
| `netmon_docsis_snmp_tables` | DOCS-IF-MIB set | Tune per modem MIB |
| `netmon_starlink_dish_address` | `192.168.100.1:9200` | Dish gRPC endpoint |
| `netmon_starlink_exporter_port` | tofu `satellite_exporter` | Exporter listen port |
| `netmon_hec_url` | derived from `cribl_edge` group | Cribl HEC endpoint |

## Secrets (SOPS)

Referenced via env lookups; add to `secrets.enc.yaml` to enable:

- `NETMON_DOCSIS_SNMP_COMMUNITY` — cable modem SNMP community (defaults to
  `public`).
- `NETMON_HEC_TOKEN` — optional; if set, Telegraf authenticates to the Cribl
  HEC input. Unset = unauthenticated push (acceptable on the mgmt VLAN).

## Installation

This role ships with the repo; no separate install step. Its only collection
dependency, `community.docker`, is pinned in the repo-root `requirements.yml`
(installed by the bootstrap playbook). Hosts are selected automatically: the
`netmon`-tagged probers from the terraform inventory are grouped into
`netmon_group` by `inventory/load_tofu.yml`, and the `netmon` play in
`playbooks/site.yml` runs this role against them.

## Usage

Run via the standard site playbook (tags `netmon`, `monitoring`, `telegraf`):

```bash
ansible-playbook playbooks/site.yml --tags netmon
```

Or include the role directly against the prober group:

```yaml
- name: Configure netmon probers
  hosts: netmon_group
  become: true
  roles:
    - role: netmon
```

## Handlers

- `Restart netmon stack` — recreates the compose stack against the rendered
  config (`recreate: always`).

## Ingestion

Cribl Edge receives the HEC push on `cribl_hec_input_port`
(`group_vars/all.yml`) and routes it through the `netmon` pipeline, which stamps
`index = netmon`. See the `cribl_edge` role and `docs/NETWORK_DIAGNOSIS.md` in
tofu-proxmox.
