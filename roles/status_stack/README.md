# status_stack

Gatus (catalog + OIDC + keystone synthetics) and Uptime Kuma (operator status
UI) as one Docker-in-LXC compose project on the tofu `status` guest.

## Split

- **Gatus** is the IaC synthetics source of record (catalog URLs, keystones,
  OIDC client probes) at `60s`, scraped by Prometheus.
- **Uptime Kuma** is the status UI. Ansible only creates the first admin via
  Kuma's own `/setup` endpoint. Monitors are not synced from Ansible — there
  is no maintained first-party API module worth depending on, and Gatus already
  covers the same keystones.

## Auth overlays

`status_stack_authenticated_endpoints` may add API-key probes when inventory
already has Homarr/OpenBao secrets. Do not invent Authelia session automation.

## Prometheus

`prometheus_group` scrapes Gatus `/metrics` when a `status`-tagged guest exists.
