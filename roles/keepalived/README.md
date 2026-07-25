# keepalived

Floats the ingress **VRRP virtual IP** across every Traefik instance so the
reverse proxy has no single-node SPOF. DNS points every fronted service at the
VIP (see the `technitium_dns` role); keepalived migrates it automatically on a
node loss or a local Traefik failure — there is no manual DR step.

## How it works

- **Unicast VRRP** (no multicast, so it works across the LXC bridge) between the
  Traefik instances. Peers, VIP, and the VRRP `virtual_router_id` are all derived
  from the tofu inventory (`tofu_data.ingress_hosts` / `ingress_vip` /
  `constants.ingress_ports.keepalived_vrid`) — no hardcoded IPs or ids.
- **Deterministic master election, no manual flag.** Priority decreases with the
  node's position in the sorted `ingress_hosts` list, so the first instance is
  MASTER and the rest are ordered BACKUPs. keepalived preempts on priority, with
  a `preempt_delay` so a flapping Traefik does not bounce the VIP twice per
  incident.
- **Health-aware.** A `track_script` — an HTTPS request to the local Traefik on
  `:443` — drops this node's priority when Traefik is down *or* wedged (listening
  but not responding), so the VIP leaves even if the process is technically alive.
- **No-op when not HA-ready.** With `< 2` ingress instances or no published VIP,
  the role skips cleanly (single-ingress / pre-HA deployments stay green).

## Requirements

- Two or more LXCs tagged `ingress` (the Traefik HA pair), on different nodes.
- tofu-proxmox publishing `ingress_vip` + `ingress_hosts` in the inventory.

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `keepalived_vip` | `tofu_data.ingress_vip` | The floating VIP. |
| `keepalived_peers_all` | `tofu_data.ingress_hosts` | All ingress instance addresses. |
| `keepalived_vrid` | `tofu_data.constants.ingress_ports.keepalived_vrid` | VRRP router id. |
| `keepalived_interface` | `eth0` | LXC NIC carrying the VLAN + VIP. |
| `keepalived_auth_pass` | `env KEEPALIVED_AUTH_PASS` | Optional unicast VRRP PASS (omitted when empty). |
| `keepalived_manage_services` | `true` | Set `false` for CI / template-render (no live service). |

## Installation

Included in this repo's Ansible collection; no separate install. The
`keepalived` package is installed on the target by the role
(`keepalived_manage_services: true`). Run from the repo root.

## Usage

Applied by `playbooks/site.yml` (Phase 8d) on the `traefik_group`, right after
the `traefik` role:

```bash
ansible-playbook playbooks/site.yml --tags ingress --limit traefik_group
```

## Failover drill

`scripts/ingress-failover-drill.sh` is an **automated, scriptable** drill (never a
manual runbook): against a live ingress pair it stops Traefik on the VIP holder,
asserts the VIP + an HTTPS probe still answer from the surviving node, then
restores. Wire it into CI where a live pair exists.
