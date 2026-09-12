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

## Monitor URLs

Each check reports to two independent deadmen every cycle. Both URLs are
derived from the check name, so a new check needs no per-check secret:

| Receiver | Report | Source of the credential |
| --- | --- | --- |
| Gatus external endpoint `deadman_<name>` | `POST …/api/v1/endpoints/deadman_<name>/external?success=<bool>&error=<msg>` with the shared bearer token | `bao_monitoring_secrets.GATUS_EXTERNAL_TOKEN` (monitoring domain) |
| Healthchecks check `<name>` | `…/ping/<ping key>/<name>` (`/fail` on a breach), `?create=1` so the check exists after the first report | `bao_monitoring_secrets.HEALTHCHECK_PING_KEY` |

The Gatus side is declared in `roles/status_stack` (`status_stack_deadman_endpoints`,
one entry per check name with its heartbeat); a name missing there is rejected by
Gatus, so add the endpoint there when adding a check here. The Healthchecks
report is skipped until a `healthchecks` backend is present in the published
ingress table; an empty token skips only that receiver. The journal entry and
ntfy alert always fire.

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
```

## Contributing

Edit in a worktree, pass `ansible-lint` (production profile) and the
`template_render` fixture, open a PR. Keep ports and hostnames sourced from the
inventory — never hardcode them here.

## License

Apache-2.0, matching the repository.
