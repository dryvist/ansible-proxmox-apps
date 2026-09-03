# status_stack

Gatus (catalog + OIDC synthetics) and Uptime Kuma (keystone status page) as one
Docker-in-LXC compose project on the tofu `status` guest.

## Cadence

Every Gatus endpoint defaults to `60s`. Uptime Kuma keystone monitors use the
same interval when the Socket.IO bootstrap client is available.

## What Gatus checks

1. **Catalog URLs** — every `dashboard_catalog` public HTTPS URL, follow
   redirects. `504` and Authelia OAuth error bodies (`invalid_client`, etc.) are
   unhealthy.
2. **Keystones** — Traefik, Authelia, Gatus, Prometheus, OpenBao, Healthchecks
   (same set as Uptime Kuma).
3. **OIDC client registration** — Authelia authorize URL per known `client_id`
   from the authelia role defaults (no login, no client secret).

## Auth overlays

`status_stack_authenticated_endpoints` may add API-key probes when inventory
already has Homarr/OpenBao secrets. Do not invent Authelia session automation.

## Prometheus

`prometheus_group` scrapes Gatus `/metrics` when a `status`-tagged guest exists.
