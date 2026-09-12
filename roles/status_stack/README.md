# status_stack

Gatus (catalog + OIDC + keystone synthetics), Uptime Kuma (operator status
UI) and AutoKuma (Kuma monitor sync) as one Docker-in-LXC compose project on
the tofu `status` guest.

## Split

- **Gatus** is the IaC synthetics source of record (catalog URLs, keystones,
  OIDC client probes, plus the `monitor_targets`-derived ICMP/TCP/HTTP checks
  below) at `60s`, scraped by Prometheus.
- **Uptime Kuma** is the status UI. Ansible creates the first admin via Kuma's
  own `/setup` endpoint; it never talks to the Kuma API directly.
- **AutoKuma** syncs Uptime Kuma monitors from `monitor_targets` via its own
  socket.io client, in static-monitors mode (one `.json` file per monitor
  under `status_stack_autokuma_static_monitors_dir`). This replaces the
  previous "no maintained first-party API worth depending on" stance — Kuma
  monitors are no longer hand-added in the UI.

## monitor_targets — one generator, two renderers

`inventory/load_tofu/monitor_targets.yml` derives ICMP/TCP/HTTP targets from
the published tofu inventory (guests, PVE nodes, and named services whose
health path is already used elsewhere in this repo — OpenBao, Cribl) and
propagates the `monitor_targets` fact to every host, the same way `tofu_data`
is propagated. Gatus and AutoKuma both render from it; nothing here
hand-declares a guest, node, or service target twice. A later Prometheus
blackbox `file_sd` package is expected to reuse the same fact.

Scoped deliberately: there is no per-guest port map in this repo (no
`host_services` fact), so guests get ICMP only. DNS query checks are out of
scope — no existing Gatus/Prometheus DNS-check pattern exists to reuse.

## Alerting

Both Gatus and AutoKuma alert to ntfy. Gatus fires the same alert for a
status failure and a slow-response failure, so the "urgent vs degraded"
routing is implemented as a criticality split by endpoint group: `keystone`/
`node`/`service` groups route to `status_stack_ntfy_topic_urgent` (priority
`status_stack_ntfy_priority_urgent`), everything else to
`status_stack_ntfy_topic_degraded`.

## Auth overlays

`status_stack_authenticated_endpoints` may add API-key probes when inventory
already has Homarr/OpenBao secrets. Do not invent Authelia session automation.

## Prometheus

`prometheus_group` scrapes Gatus `/metrics` when a `status`-tagged guest exists.

## Installation

This role ships with the repo; no separate install step. Its only collection
dependency, `community.docker`, is pinned in the repo-root `requirements.yml`.
Hosts are selected from the terraform inventory: the `status`-tagged guest is
grouped into `status_group` by `inventory/load_tofu.yml`, and the
`playbooks/site/04-secrets-and-collab-apps.yml` play runs this role against it.

## Usage

Run via the standard site playbook (scoped — never the full `site.yml`):

```bash
ansible-playbook playbooks/site.yml --tags status
```

Or include the role directly against the status host:

```yaml
- name: Configure the status stack
  hosts: status_group
  become: true
  roles:
    - role: status_stack
```
