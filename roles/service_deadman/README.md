# service_deadman

A timer-driven liveness watchdog for the cluster's keystone single-points-of-
failure (DNS, the Traefik ingress, the syslog/netflow load balancer). It turns a
**silent** keystone failure into a page.

## Why

The shared-infra keystones are concentrated on one node. Restart-on-failure
drop-ins make them self-heal, but a service that exhausts its restart budget — or
hangs while systemd still reports it `active` — fails silently. This role adds
the missing **visibility** layer, mirroring the proven `download_vpn`
killswitch-validator pattern.

```text
systemd timer (every 60s)
  -> validator script
       per keystone on this host: run a functional probe
         healthy  -> ping healthchecks OK + Kuma push status=up
         breached -> journal + ntfy alert + healthchecks /fail + Kuma status=down
```

Because both monitors expect a ping every cycle, a missed run (validator crash,
host down) **also** pages — true deadman semantics, from two independent
monitors.

## How it works

Checks are declared per inventory group in `service_deadman_group_checks`. The
role selects every check whose group this host belongs to (`group_names`), so a
single `site.yml` play can target the union of keystone groups and each host
watches only its own services. A host with no matching checks is a no-op.

Each check is a functional probe (not merely `systemctl is-active`), with unit
names verified against the live services:

| Group | Service | Probe |
| --- | --- | --- |
| `technitium_dns_group` | `dns.service` | unit active **and** `dig @127.0.0.1 . NS` answers |
| `traefik_group` | `traefik.service` | unit active **and** TCP 443 accepts a connection |
| `haproxy_group` | `haproxy.service` | unit active (TCP VIP) |
| `haproxy_group` | `nginx.service` | unit active (UDP syslog/netflow LB) |
| `docker_vms` | `github-runner@N.service` (pool) | every configured replica unit active |
| `docker_vms` | Docker data disk | `/var/lib/docker` used percent below `service_deadman_disk_floor_pct` |
| `ntfy_group` | `ntfy` (roles/ntfy_docker) | `curl` to the local `/v1/health` endpoint returns 200 |

## Monitor URLs

Each check reports to independent deadmen every cycle. Every URL is derived
from the check name, so a new check needs no per-check secret:

| Receiver | Report | Credential |
| --- | --- | --- |
| Gatus external endpoint `deadman_<name>` | `POST …/api/v1/endpoints/deadman_<name>/external` | `bao_monitoring_secrets.GATUS_EXTERNAL_TOKEN` |
| Uptime Kuma push monitor `<name>` | `…/api/push/<token>?status=up\|down`, token derived from the Gatus token | same token |
| Healthchecks check `<name>` (self-hosted) | `…/ping/<ping key>/<name>`, `/fail` on breach | `bao_monitoring_secrets.HEALTHCHECK_PING_KEY` |
| Off-site healthchecks deadman `<name>` | same wire form, different (third-party) base URL | `bao_monitoring_secrets.HEALTHCHECKS_OFFSITE_PING_URL` |

Details each receiver's report format omits: Gatus takes `success=<bool>&error=<msg>`;
Kuma's push token is `sha256("<gatus token>:<name>")[:20]`; the two Healthchecks
rows both append `?create=1` so the check exists after the first report, and
`/fail` on a breach. The off-site row's URL, unique id included, is the whole
credential — no separate ping key.

The Gatus endpoints and the Kuma push monitors are both rendered by
`roles/status_stack` from `status_stack_deadman_endpoints` (one entry per check
name with its heartbeat); a name missing there is rejected by Gatus and unknown
to Kuma, so add the entry there when adding a check here. The Healthchecks
report is skipped until a `healthchecks` backend is present in the published
ingress table; an empty URL/token skips only that receiver, self-hosted or
off-site. The journal entry and ntfy alert always fire.

The off-site receiver is the one exception worth calling out: it is a
free-tier SaaS deadman, reachable from the open internet, not the homelab.
It is the only receiver that still pages when the homelab itself — ingress,
DNS, or the self-hosted Gatus/Kuma/Healthchecks stack — is unreachable. It
is unseeded (empty, skipped) by default; seed
`secrets-external/platform/healthchecks-offsite` in OpenBao to enable it.

## Installation

No manual install. The role is wired into `playbooks/site.yml` and runs against
the keystone groups on every converge. It deploys a validator script plus a
systemd service + timer; no extra packages are required (`curl`, `dig`, and
`logger` are already present on the infra LXCs). Ansible collection dependencies
come from the repo `requirements.yml`.

## Usage

Wired into `playbooks/site.yml` against the keystone groups. Target just this
role by tag:

```bash
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags service_deadman --limit technitium_dns_group:traefik_group:haproxy_group,localhost
```

## Verification

```bash
# On a keystone host:
systemctl status service-deadman-validate.timer
/usr/local/bin/service-deadman-validate.sh; echo "rc=$?"   # 0 = all healthy

# Simulate a failure (e.g. stop a watched unit) and confirm a page:
#   - journal: journalctl -t service-deadman
#   - ntfy:    the "keystone" topic receives an urgent message
#   - healthchecks: the corresponding check flips to down
#   - Uptime Kuma: the corresponding push monitor flips to down
#   - off-site healthchecks: the corresponding check flips to down (once seeded)
```

## Contributing

Edit in a worktree, pass `ansible-lint` (production profile) and the
`template_render` fixture, open a PR. Keep ports and hostnames sourced from the
inventory — never hardcode them here.

## License

Apache-2.0, matching the repository.
