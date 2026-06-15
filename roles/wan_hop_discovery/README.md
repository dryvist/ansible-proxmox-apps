# wan_hop_discovery

Resolve the **current first-N echo-reachable public WAN hops** (the ISP path)
dynamically at deploy time and expose them as the host fact
`wan_hop_discovery_isp_hops`. The `prometheus_stack` (blackbox `icmp`) and
`network_quality` (smokeping_prober) roles fold this fact into their probe-target
lists, so they always probe the **live** ISP edge — without any real WAN IP ever
being committed to this public repo.

## Why dynamic instead of a static private inventory

The Comcast WAN side renumbers with no hardware change: CGNAT lease changes, CMTS
re-homing, and per-flow ECMP all move the hop IPs. A hand-listed hop in a private
`group_vars` file rots silently — you end up probing a dead IP and reading it as an
ISP outage. Discovery resolves "whatever the first public hops are *right now*"
every deploy.

## Why ICMP-echo validation is mandatory

smokeping_prober and blackbox's `icmp` module probe with **ICMP echo**. Many routers
answer traceroute's TTL-expiry but silently drop direct echo — the Comcast **CGNAT
edge (`100.64.0.0/10`) does exactly this**. Probing such a hop would read as 100%
loss and fire a false ISP-down alert. The role pings each candidate and keeps only
echo responders; the CGNAT demarcation is dropped automatically, leaving the first
Comcast routers that actually answer.

## Algorithm

1. `mtr -n -r -c<cycles> -j <anycast>` traces the path to a stable anycast target.
2. Drop RFC1918 LAN hops and unresponsive (`???`) hops. CGNAT `100.64/10` is kept as
   a *candidate* (echo-validation decides its fate).
3. Ping-validate every candidate; keep the order-preserving echo-reachable subset.
4. Keep the first `wan_hop_discovery_max_hops` of those as the ISP-path targets.
5. Persist the set to a host-local state file. On the next run, reuse it while every
   member still answers echo (idempotent — no prober churn); re-discover only when
   the path has renumbered (auto-heal).

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `wan_hop_discovery_probe_target` | `1.1.1.1` | Stable anycast destination to trace toward |
| `wan_hop_discovery_cycles` | `5` | mtr report cycles (steadier under ECMP) |
| `wan_hop_discovery_max_hops` | `3` | How many echo-reachable public hops to keep |
| `wan_hop_discovery_private_regex` | RFC1918 | LAN space to drop (CGNAT deliberately excluded) |
| `wan_hop_discovery_state_file` | `/var/lib/wan-hop-discovery/isp_hops.json` | Persisted set for idempotent reuse |

## Output

Host fact **`wan_hop_discovery_isp_hops`** — a list of echo-reachable public ISP-path
hop IPs (possibly empty, in which case consumers fall back to modem + anycast only).

## Installation

This role ships with the repo; no separate install step and no collection
dependencies (it uses only `ansible.builtin` modules plus `mtr` + `ping`, which the
role installs via `wan_hop_discovery_packages`). Hosts come from the terraform
inventory: the metrics LXC (`prometheus` hostname / `monitoring` tag) is grouped by
`inventory/load_tofu.yml`, and the discovery play in `playbooks/site.yml` runs this
role against it ahead of the `prometheus_stack` and `network_quality` plays.

## Usage

Run as its own play *before* the monitoring plays so the fact is set for the same
host within the run:

```yaml
- name: Discover the live WAN ISP path
  hosts: prometheus_group
  become: true
  gather_facts: false
  roles:
    - role: wan_hop_discovery
```

Consumers reference `wan_hop_discovery_isp_hops | default([])`, so a scoped run that
skips discovery degrades safely to modem + anycast targets.
