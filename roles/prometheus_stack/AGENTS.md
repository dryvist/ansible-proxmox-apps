# prometheus_stack

This role deploys Prometheus and its exporters. It holds no Prometheus content.

- Alert and recording rules live in `dryvist/prometheus-homelab-rules`.
- sql_exporter collectors (metric definitions and their SQL) live in
  `JacobPEvans/prometheus-sql-exporter-collectors`.
- The role checks each repository out at a pinned commit that Renovate moves.

Never add a rule file, a collector, a query or a dashboard under this role. Add
it to the content repository, then let the pin move here. A change here is
limited to how the content is fetched, mounted and verified, and to the
read-only database grants the collectors need.
