# cribl_stream

Deploy Cribl Stream as central processing node.

## Purpose

Installs and configures Cribl Stream as a processing node in the log pipeline.
Receives events from Cribl Edge nodes, applies transformations, and forwards
to outputs. Persists data to 100GB mounted queue disk at `/opt/cribl/data`.

## Requirements

- Debian-based OS
- 100GB persistent disk mounted at `/opt/cribl/data`
- Network connectivity to Cribl Edge nodes
- Sufficient CPU and memory for log processing

## Role Variables

All variables in `defaults/main.yml` are user-configurable.

### Key Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `cribl_stream_service_state` | started | Service state |
| `cribl_stream_service_enabled` | true | Enable on boot |
| `cribl_stream_mode` | worker | Role in cluster |

## Examples

### Basic Deployment

```yaml
- name: Deploy Cribl Stream
  hosts: cribl_stream_group
  roles:
    - cribl_stream
```

## Post-Installation Configuration

Configure data pipeline via Cribl Web UI after Ansible deployment:

1. Access Stream UI (`http://cribl-stream:9000`)
2. Configure data sources (inputs from Edge nodes)
3. Use the installed `cc-stream-apple-mlx-metrics` and
   `cc-stream-cribl-internal-telemetry` packs for generic processing. Source
   connections select their pipelines with `pack:<pack-id>` references rather
   than local copies.
4. Configure outputs (Splunk, etc.)

### Grafana alert delivery

Grafana posts unified-alerting envelopes to the Stream HEC raw endpoint with
`sourcetype=grafana:alert`. The same HEC input keeps the complete envelope in
the `ansible` Splunk index and sends a compact, byte-bounded summary through
`grafana_alerts_ntfy` to the existing `observability` ntfy hub. The hub owns the
existing Slack and Zammad fan-out. Large notifications become numbered
continuations; the formatter retains every alert record and source link in the
summary while Splunk retains the complete Grafana envelope.

The ntfy leg receives only `grafana:alert:canary` events while
`cribl_stream_grafana_ntfy_cutover_verified` is false (the default), and the
existing direct Grafana webhook remains active. Set the flag true only after
successful receipts confirm the ntfy hub's Slack and Zammad destinations; this
adds production Grafana alerts to ntfy while continuing to accept canaries, and
leaves the direct webhook for critical Nautobot drift. A verified cutover
requires a configured ntfy URL.

The Nautobot drift role posts one HEC JSON event per run with its separate
`cribl_stream_nautobot_drift_hec_token`. Every drift event continues to Splunk,
while only `critical` events reach the direct Slack webhook through
`grafana_alerts_slack` as a readable one-line summary. That direct leg keeps
its existing persistent-queue and backpressure settings.

## Tasks

- Install Cribl Stream package
- Ensure service is running
- Configure persistent queue location
- Set up processing node mode
- Collect LiteLLM's official model price file daily as one small Splunk event
  per model with both base rates

## Admin Login Checks

`--tags cribl_stream_admin` makes one vendor-default login attempt and reports
only its HTTP status. If the default is accepted, the role rotates it to the
configured managed credential and verifies that credential.

For a read-only follow-up, use
`--tags cribl_stream_admin_probe --extra-vars cribl_stream_admin_probe_only=true`.
It makes one vendor-default attempt, reports only its HTTP status, and verifies
the configured credential without changing files or restarting Cribl.

## Handlers

- `restart cribl stream`: Restart the Cribl Stream service
