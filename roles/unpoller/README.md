# unpoller

Install [unpoller](https://unpoller.com) (the UniFi controller poller) as a
pinned-version native systemd service, exposing a Prometheus `/metrics`
endpoint on port `9130`: per-port, per-VLAN and WAN counters, client counts,
and AP/gateway health the UniFi controller does not stream natively.

This is the same controller-staged-binary pattern as `roles/node_exporter`
(#2162): the release tarball is fetched once on the Ansible controller
(unrestricted egress) and copied to the guest, since this guest sits behind
the `outbound-internal` firewall group.

## Where it runs

Deployed on the Cribl Stream guest (`cribl_stream_group`) rather than a new
guest or a Docker container — Cribl Stream is already the metrics hub for
this estate and scrapes `localhost:9130` directly with its native Prometheus
scraper source, fanning the samples out to `victoriametrics_rw` and the
Splunk metrics index (`roles/cribl_stream`). See
`playbooks/site/02-dns-and-pipeline.yml`.

**This is a second, independent unpoller instance.** `roles/unifi_metrics`
already runs unpoller + Telegraf as a Docker-in-LXC stack on a dedicated
`unifi-metrics` guest, shipping Splunk-HEC through Cribl Edge to
`index=unifi_metrics`. That deployment is unchanged (installed = intentional
— see the org's data-duplication policy); this role is the native-systemd,
Cribl-Stream-scraped path requested separately. Both poll the same
controller API independently.

## Credentials

- **Controller URL** (`UNIFI_API`): the same OpenBao-backed environment
  variable (`secret/infrastructure/unifi`, field `UNIFI_API`) the
  `unifi_metrics` role and the `tofu-unifi` provider already treat as the
  single source of truth for the controller address. Must be an FQDN — the
  role asserts it is not a literal IPv4 URL.
- **Controller account**: neither UniFi Terraform provider
  (`ubiquiti-community/unifi`, `filipowm/unifi`) exposes a resource for a
  controller local-admin/API user — only RADIUS accounts and network
  clients. The read-only `unpoller` account is therefore created by hand,
  once, in the controller UI (Settings → Admins → Local Access Only,
  read-only role) — the same way the provider's own bootstrap admin exists.
  Only the **password** is automated: generated once into OpenBao
  (`secret/apps/unpoller`, field `unpoller_controller_password` —
  `roles/openbao/defaults/main/01c-app-secrets-generated.yml`) and read here
  bao-first with an env fallback (`UNPOLLER_CONTROLLER_PASSWORD`).

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `unpoller_version` | (set in `inventory/group_vars/all.yml`, Renovate-managed) | Pinned upstream release |
| `unpoller_metrics_port` | `9130` (`cribl_stream_group.yml`, shared with `roles/cribl_stream`'s scrape target) | Prometheus exporter port |
| `unpoller_controller_url` | `$UNIFI_API` | Controller URL (FQDN) |
| `unpoller_controller_user` | `unpoller` | Read-only controller account |
| `unpoller_controller_password` | OpenBao `apps/unpoller` | Generated once, rotatable standalone |
| `unpoller_controller_verify_ssl` | `false` | UDW/UDM ships a self-signed cert |
| `unpoller_sites` | `all` | Sites to poll |

## Installation

No collection dependency: every task uses `ansible.builtin` modules.
Consumed as an ordinary role dependency from `playbooks/site.yml`; nothing
to install separately.

## Usage

```bash
ansible-playbook -i inventory playbooks/site.yml --tags unpoller
```

Verify: `curl http://<guest>:9130/metrics | head` should show `unpoller_*`
and `unifi_*` metric families within a couple of scrape intervals of a
Cribl Stream converge.
