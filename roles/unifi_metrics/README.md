# unifi_metrics

Ships **all** UniFi controller telemetry into Splunk: device CPU / memory /
temperature / uptime, per-port bytes / errors / drops / PoE / STP, per-client
signal / TX-RX rate / satisfaction, WAN uplink quality, and controller health.

## Why this shape

Telegraf has no native UniFi input — its only built-in path is SNMP, which
misses device CPU/mem, client satisfaction, and WAN quality. The canonical
full-fidelity collector is [unpoller](https://unpoller.com), which polls the
same controller API the UniFi dashboard uses. unpoller exports Prometheus (not
Splunk HEC), so this role mirrors the `netmon` **satellite** path — an exporter
scraped by a Telegraf `inputs.prometheus`, shipped Splunk-HEC to Cribl Edge:

```text
unpoller  ──poll──>  UniFi controller (UDW)
unpoller  ──:9130/metrics (Prometheus)
telegraf  ──inputs.prometheus scrape──>  outputs.http (splunkmetric HEC)
          ──>  Cribl Edge in_netmon_hec  ──(stream=unifi_metrics branch)──>
          ──>  Splunk index=unifi_metrics
```

All collection is an off-the-shelf exporter + a native Telegraf input — no
scripts.

## Index routing

The Telegraf agent tags every metric `stream=unifi_metrics`. It reuses the
shared Cribl Edge HEC input (`in_netmon_hec`); the Cribl `netmon` pipeline
branches on the `stream` tag so these events land in `index=unifi_metrics`
while the per-WAN probers (no `stream` tag) continue to `index=netmon_metrics`.

## Installation

Deployed by the standard site playbook as a role on the `unifi_metrics`
inventory group; it installs Docker-in-LXC and runs the unpoller + Telegraf
compose stack. Prerequisites:

- A target LXC (the `unifi_metrics` group) able to reach the UniFi controller
  and the Cribl Edge HEC port.
- `UNIFI_API` / `UNIFI_USERNAME` / `UNIFI_PASSWORD` in the environment of the
  Ansible run (the `network` keychain items, same creds the tofu-unifi provider
  uses). A read-only UniFi local admin is sufficient and recommended.
- The `cribl_edge` group deployed (provides the HEC input + `unifi_metrics`
  index branch) and a Splunk `unifi_metrics` index (terraform-proxmox).

## Usage

```bash
ansible-playbook -i inventory playbooks/site.yml --tags unifi_metrics
```

Controller creds are passed into the unpoller container's `environment:` (the
rendered compose is `0600` on the single-purpose LXC, never committed). Verify
in Splunk: `index=unifi_metrics | stats count by host` should show the UniFi
devices within a couple of scrape intervals.

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `unifi_metrics_controller_url` | `$UNIFI_API` | Controller URL (prefer FQDN) |
| `unifi_metrics_controller_user` / `_pass` | `$UNIFI_USERNAME` / `$UNIFI_PASSWORD` | Controller creds (env only) |
| `unifi_metrics_controller_verify_ssl` | `false` | UDW ships a self-signed cert |
| `unifi_metrics_sites` | `["all"]` | Sites to poll |
| `unifi_metrics_unpoller_port` | `9130` | Prometheus exporter port (local) |
| `unifi_metrics_telegraf_interval` | `30s` | Scrape + flush interval |
| `unifi_metrics_hec_url` | derived from `cribl_edge` group | Cribl HEC endpoint |
