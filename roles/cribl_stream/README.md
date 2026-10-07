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
3. Define transformation pipelines
4. Configure outputs (Splunk, etc.)

### Grafana alert delivery

Grafana posts unified-alerting envelopes to the Stream HEC raw endpoint with
`sourcetype=grafana:alert`. The same HEC input sends the event to the `ansible`
Splunk index and through `grafana_alerts_slack`, which drops other sourcetypes
before delivering to the configured Slack-compatible webhook. The notification
path is Grafana → Cribl Stream → Splunk and webhook; it does not use the ntfy
service.

## Tasks

- Install Cribl Stream package
- Ensure service is running
- Configure persistent queue location
- Set up processing node mode

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
