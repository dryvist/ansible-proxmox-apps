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

An optional Collector leg forwards original spans over OTLP/HTTP before the
trace-storage legs apply their transformations. Set
`cribl_stream_otel_collector_enabled: true` after receiver and export validation;
it defaults to false. Inventory derives `cribl_stream_otel_collector_url` from
the `clickhouse_group` application address and published `otel_traces_http`
port. The trace-only pipeline preserves IDs, timestamps, and resources.
Its bounded error queue drops on overflow so the trace-storage legs can
continue during a Collector outage. Disabling the flag removes its connection
and destination on converge. The pipeline registry excludes it when disabled;
an already deployed pipeline directory remains inert until explicit cleanup.
Collector-derived span and service-graph metrics still need live acceptance.

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

The 2026-11-06 source audit covers 35 roles: 1 source-supported Edge candidate
and 2 provisional containers. Effective logging settings and receipt in Stream
remain **UNKNOWN** for every row; source configuration does not prove delivery.

| Scope | Source configuration | Edge disposition |
| --- | --- | --- |
| `agent_sandbox` / Squid | Unmounted image-default `/var/log/squid/`. | 1 source-supported directory-level candidate. |
| Dify / `ssrf_proxy` | Same pinned Squid image; no log mount or redirect. | Provisional; pinned startup artifacts must confirm file-only output. |
| Dify / `agent_ssrf_proxy` | Same image and bounded inference. | Provisional; pinned startup artifacts must confirm file-only output. |
| Zammad | Native package files outside Docker. | No container Edge candidate. |
| Sim | Documented stdout; vendor Compose unavailable. | No file-only candidate established. |
| ClickHouse, SQL Server, Home Assistant, Homepage | Host-mounted log directories. | Prefer native host-file forwarding when needed. |
| Runner services | Host diagnostics and runtime files. | No additional container Edge justified. |
| Remaining audited containers | Explicit or inherited drivers; destinations vary or are UNKNOWN. | No additional Edge justified by current evidence. |

The candidate list is not exhaustive until UNKNOWN application destinations are
resolved. Exact Squid filenames and live behavior remain UNKNOWN. Runner
diagnostics have a host mount and rsyslog file input; Kubernetes runtime files
are host-visible, but runner diagnostic export remains UNKNOWN. Host mounts do
not establish collection or complete console output.

The sandbox evidence is in `roles/agent_sandbox/templates/squid.conf.j2` and
`roles/agent_sandbox/templates/docker-compose.yml.j2`. Its existing Edge inputs
cover session spools and the allowlist audit, not the Squid log directory.
Dify's [proxy configurations](https://github.com/dryvist/ansible-proxmox-ai/tree/develop/roles/dify_docker/templates)
support only a provisional inference: the
[Squid image documentation](https://hub.docker.com/r/ubuntu/squid) describes both
a file-log volume and Pebble logs. Inspect the pinned startup/configuration
artifacts before classifying either Dify proxy as file-only. Evaluate Squid's
native syslog/TCP access logging before adding Edge; establish cache/admin log
handling separately. Eligibility does not authorize deployment.

Zammad's package tasks are in `roles/zammad/tasks/main/elasticsearch_and_package.yml`;
[Zammad logging](https://docs.zammad.org/en/latest/appendix/privacy.html)
and [environment settings](https://docs.zammad.org/en/latest/appendix/environment-variables.html)
describe `/opt/zammad/log/` and native `RAILS_LOG_TO_STDOUT` output. Elasticsearch
also uses native file logs. [Sim observability](https://docs.sim.ai/platform/self-hosting/observability)
does not verify the pinned vendor Compose artifact; the local
[Compose override](https://github.com/dryvist/ansible-proxmox-ai/blob/develop/roles/sim_docker/templates/docker-compose.override.yml.j2)
sets images and data volumes without specifying logging. Sim's effective service
inventory, drivers, mounts, cron logging, and OTEL settings remain UNKNOWN;
documented app/realtime stdout and PostgreSQL workflow history do not resolve them.

Docker defaults in `roles/docker_engine/defaults/main.yml` declare journald for
this repository. Other role sources either declare journald explicitly or leave
the driver to the daemon; unavailable vendor configuration stays UNKNOWN.
Existing containers retain their driver until recreated. The daemon default
establishes neither application log destinations nor effective container drivers,
journald-to-rsyslog ingestion, or receipt in Stream. Keep non-file-only streams on
journald to rsyslog to Stream, or direct OTEL, with delivery verified separately.
Host-visible files can use the existing rsyslog imfile inputs, which default empty.
For a verified container-only file stream, record paths and rotation before
configuring a native Edge file source and Stream connection.
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
