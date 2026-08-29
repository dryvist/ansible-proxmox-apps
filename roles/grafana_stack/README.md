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

Vendored dashboards live in `files/dashboards/` (currently Grafana.com 25255,
"Claude Code Metrics (Prometheus)", pinned to the provisioned datasource uid).
Add a dashboard by dropping its JSON there — the provider picks it up on the
next converge.
