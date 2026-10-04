# grafana_stack

Grafana OSS + VictoriaMetrics single-node as a single Docker-in-LXC compose
stack (one project, two services, both host networking). The AI coding-agent
observability backend — contract in terraform-proxmox
`docs/AI_OBSERVABILITY.md`.

- **VictoriaMetrics** receives Prometheus `remote_write` from the stream
  pipeline and is the sole Grafana datasource (provisioned, uid
  `victoriametrics`). Retention defaults to 2y;
  `-opentelemetry.usePrometheusNaming` keeps OTLP-originated metric names in
  the Prometheus form the dashboards query.
- **Grafana** is Traefik-fronted (Authelia-gated vhost); dashboards and the
  datasource are file-provisioned read-only, so the UI carries no hand-built
  state and rebuilds clean. The admin password is generated on first converge
  and persisted (homarr-style decide/persist pattern).

Ports come from the tofu `service_ports` constants
(`grafana_web`/`victoriametrics`) with upstream defaults as fallback. Docker
itself comes from the `docker_engine` meta dependency; `daemon.json` is owned
by the registry-mirror play in `site.yml`, never written here.

Dashboards come from
[`dryvist/grafana-dashboards`](https://github.com/dryvist/grafana-dashboards)
at the release tag in `grafana_stack_dashboards_version` (Renovate bumps it).
The role extracts that release's `dashboards/*.json` into the provisioned
dashboard directory; add or change a dashboard in that repository, not here.

Skipped: grafana.com dashboard 24641 ("OpenAI Codex (VictoriaStack)") — every
panel in it queries a logs or traces datasource (VictoriaLogs / Jaeger); none
of its panels query Prometheus-compatible metrics, so remapping it to
`victoriametrics` would ship a dashboard where 100% of panels error rather
than populate.

## AI alert rules

`templates/alerting/rules-ai.yml.j2` provisions four Grafana-managed rules in
the `ai-observability` group, all delivered through the existing contact
point:

- `llm-router-down`: every `llm_router` scrape target is down or missing.
- `llm-judge-failing`: at least half of the router's `judge` role requests
  failed over 15 minutes.
- `hermes-llm-failures`: Hermes virtual keys returned server errors over 15
  minutes.
- `zdr-key-non-zdr-model`: a key in `grafana_stack_alert_zdr_only_keys`
  requested a model in `grafana_stack_alert_zdr_false_models`.

## Installation

Included via `requirements.yml`/`meta/main.yml` like any other role in this
collection; not installed standalone. Add it to a play's `roles:` list.

## Usage

```yaml
- hosts: grafana_group
  roles:
    - grafana_stack
```

## Dashboard metric sources

The provisioned dashboards read two families of metrics:

- `claude_code_*` — emitted by the coding agent's own metrics exporter.
- `claude_jsonl_*` — emitted by a collector that runs on workstations, not on
  the host this role configures. It reads local session logs for the
  fields the exporter does not report: the ephemeral cache TTL split, thinking
  tokens, subagent attribution, and injected-context volume by kind.

The collector is installed by the workstation configuration, so it lives there
rather than here — a file this repository ships but cannot install would be a
trap for whoever tries to deploy it. Renaming a `claude_jsonl_*` metric
therefore touches two repositories; the panel descriptions name every metric
they depend on so the contract is greppable from this side.

A dashboard whose panels read `No data` for `claude_jsonl_*` series means the
collector is not running or not reaching the store; the `claude_code_*` panels
are unaffected and still populate.
