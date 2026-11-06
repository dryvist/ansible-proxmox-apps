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

### Focused converges

Run a focused component against the Stream group and localhost:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags <entry> --limit cribl_stream_group,localhost
```

| Entry tag | Work selected |
| --- | --- |
| `cribl_stream_install` | Packages, service user, tarball install or upgrade, and systemd setup |
| `cribl_stream_settings` | Worker sizing and system settings |
| `cribl_stream_inputs` | Inputs and OTLP listener proof |
| `cribl_stream_outputs` | Outputs configuration |
| `cribl_stream_pipelines` | Pipeline configuration and lookup tables |
| `cribl_stream_bmc_collector` | BMC collector, with pipeline configuration as a prerequisite |
| `cribl_stream_litellm_prices` | LiteLLM price collector, with outputs and pipelines as prerequisites |
| `cribl_stream_github_actions` | GitHub Actions collectors, with outputs and pipelines as prerequisites |
| `cribl_stream_probe` | Read-only admin login probe; add `--extra-vars cribl_stream_admin_probe_only=true` |
| `cribl_stream_admin` | Admin credential rotation and verification |

The existing `cribl_stream` tag still selects the full Cribl Stream role. Shared
assertions, unit checks, and service convergence run for Cribl entry tags. Run
`cribl_stream_install` first on a new guest; the other entries assume the Cribl
binary and service unit already exist. The `unpoller` and `cribl_packs` plays
keep their existing selectors.

## Post-Installation Configuration

Configure data pipeline via Cribl Web UI after Ansible deployment:

1. Access Stream UI (`http://cribl-stream:9000`)
2. Configure data sources (inputs from Edge nodes)
3. Use the installed `cc-stream-apple-mlx-metrics` and
   `cc-stream-cribl-internal-telemetry` packs for generic processing. Source
   connections select their pipelines with `pack:<pack-id>` references rather
   than local copies.
4. Configure outputs (Splunk, etc.)

Every log-bearing input uses `ansi_csi_strip` before routing; Splunk HEC outputs keep `secret_redaction` for credentials.

### LLM span metrics (beta)

The OpenTelemetry input sends original spans to `otel_traces_to_metrics`
before the independent trace-storage legs apply sampling or trace-ID changes.
Native Aggregations is configured to emit cumulative `llm_span_calls`, `llm_span_errors`,
`llm_span_input_tokens`, `llm_span_output_tokens`, and the
`llm_span_duration_seconds` histogram through the existing VictoriaMetrics
remote-write destination every 10 seconds. Only spans with `gen_ai.*`
attributes qualify; labels are `service_name`, `model`, `system`, and `status`.
Missing token usage is excluded from token sums. Missing or invalid timing is
excluded from the histogram while calls still count. These are span counts,
so nested agent and router spans can represent the same inference request.

After converge, capture the new pipeline's input and output during real LLM
calls and query VictoriaMetrics for `{__name__=~"llm_span_.*"}`. Confirm native
histogram serialization, including sum, count, and cumulative buckets through
`+Inf`, and verify the same original spans still reach the trace stores.

### Agent telemetry

The OpenTelemetry (OTEL) and Cribl-to-Cribl inputs fan extracted spans to
Langfuse, Phoenix, Splunk HTTP Event Collector (HEC), and Arize AX. Logs and
metrics retain their Splunk and VictoriaMetrics connections.

Every OTEL leg adds `agent`, `tier`, `privacy_class`, `model`, `accelerator`,
`caller`, and `correlation_id` to the event attributes. Canonical attributes
take precedence over `litellm.metadata.*` aliases and top-level fields. Missing,
null, empty, or invalid values receive defaults from
`defaults/main/41-agent-telemetry.yml`: tier `2`, privacy class `private`, and
`unknown` for the remaining tags. Numeric tier strings become numbers.

Destination URLs and credentials are role inputs:

| Destination | URL variable | Authentication variables |
| --- | --- | --- |
| Langfuse | `cribl_stream_langfuse_url` | `cribl_stream_langfuse_public_key`, `cribl_stream_langfuse_secret_key` |
| Phoenix | `cribl_stream_phoenix_url` | `cribl_stream_phoenix_api_key` |
| Splunk HEC | `cribl_stream_splunk_hec_url` | `cribl_stream_splunk_hec_token` |
| Arize AX | `cribl_stream_arize_url` | `cribl_stream_arize_api_key`, `cribl_stream_arize_space_id` |

Arize inputs default to the `ARIZE_OTLP_ENDPOINT`, `ARIZE_API_KEY`, and
`ARIZE_SPACE_ID` environment variables. Required values fail closed when absent.
OTLP URL inputs are base URLs; the destination appends the signal path.

The Arize connection and output post-processing pipeline both accept only
extracted spans whose normalized `privacy_class` equals `public`. Native
Drop and Eval functions retain only the 7 canonical tags and span identifiers,
timing, kind, and status code. The projection resets the span name, resource,
and scope, and removes prompt, completion, message, event, link, host, address,
and resource identity attributes. The output adds no system fields and uses
verified TLS. [Cribl Eval](https://docs.cribl.io/stream/eval-function/) and the
[OTLP destination](https://docs.cribl.io/stream/destinations-otel/) define these native functions and output settings.

### Cribl Edge log audit

Source audit dated 2026-11-06; deployed logging configuration is unverified.

| Scope | Source configuration | Edge disposition |
| --- | --- | --- |
| Zammad | Package and system services; application-file output unverified. | Candidate; no file-only stream established. |
| Sim | Compose override sets images and data volumes. | Candidate; merged vendor logging unverified. |
| Other containers | Docker defaults to journald; baseline supplies rsyslog. | Retain journald, rsyslog, and Stream, or direct OTEL. |

The Zammad package tasks are in `roles/zammad/tasks/main/elasticsearch_and_package.yml`;
Docker defaults are in `roles/docker_engine/defaults/main.yml`. Sim's source is the
[Compose override](https://github.com/dryvist/ansible-proxmox-ai/blob/develop/roles/sim_docker/templates/docker-compose.override.yml.j2).
This audit establishes no additional container requiring Edge. Install Edge only
for a verified file-only log stream inside a container: record its path and
rotation behavior, and configure the native file source and Stream connection.
Existing containers retain their logging driver until recreated; the daemon
default alone does not establish their effective driver.
[Docker logging configuration](https://docs.docker.com/engine/logging/configure/)
describes that lifecycle.

### Grafana alert delivery

Grafana posts unified-alerting envelopes to the Stream HEC raw endpoint with
`sourcetype=grafana:alert`. JSON Unroll emits one Splunk event per alert while
retaining the webhook's top-level fields, and the same HEC input sends a
compact, byte-bounded summary through `grafana_alerts_ntfy` to the existing
`observability` ntfy hub. The hub owns the
existing Slack and Zammad fan-out. Large notifications become numbered
continuations; the formatter retains every alert record and source link in the
summary.

While `cribl_stream_grafana_ntfy_cutover_verified` is false (the default), the
ntfy leg receives canaries and Grafana alerts carrying `ntfy: "true"`; the
direct Slack leg keeps all other Grafana alerts. Tagged Grafana alerts leave
the direct Slack leg and use the ntfy hub's existing Slack and Zammad fan-out.
Set the flag true only after successful receipts confirm the ntfy hub's Slack
and Zammad destinations; this adds all production Grafana alerts to ntfy while
continuing to accept canaries, and leaves the direct webhook for critical
Nautobot drift. A verified cutover requires a configured ntfy URL.

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
