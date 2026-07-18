# Phase 1 — Absorption Status & Native-Coverage Roadmap

Status of the read-only absorption effort (#977 gates 1-4). Nautobot is the
system of record for everything it can natively model; this page records what is
absorbed today and the roadmap to model **everything Nautobot is natively
capable of**.

## Absorbed today (verified live, read-only)

The converge-owned seed pipeline (`roles/nautobot`, gated by `nautobot_build_seed`
+ `nautobot_run_seed_jobs`) imports from the sibling-repo sources via additive
SSoT DiffSync jobs. Current modeled coverage, all verified against source:

| Domain | Nautobot model | Source | State |
| --- | --- | --- | --- |
| VLANs | VLAN | network defs (`NAUTOBOT_SEED_NETWORKS`) | ✅ complete |
| Prefixes/subnets | Prefix | network defs | ✅ complete |
| Fixed-IP reservations | IPAddress | UniFi fixed-ips | ✅ complete |
| Guests (containers/VMs) | VirtualMachine (+ cluster, eth0, primary IP) | tofu inventory | ✅ complete |
| Guest tags → groups | Tag | tofu inventory | ✅ complete |
| Proxmox nodes | Device (role pve-node) | Ansible hosts | ✅ complete |
| Rack servers | Device / Rack | SOPS (optional) | ⚠️ retained; source file absent |

**Drift = 0** on all modeled domains (guests 1:1, tags 1:1). The GraphQL dynamic
inventory answers with **1:1 group parity** against the tofu inventory
(verified at the data layer: identical host set, identical tag→group membership).

## Consumption contracts (verified ready, not cut over)

- **GraphQL dynamic inventory** (`inventory/nautobot.yml`): 1:1 parity confirmed.
  Local `ansible-inventory` needs `pynautobot` in the dev shell to run the plugin
  (nix-devenv gap — tracked); the converged controller has it.
- **Export artifact** (`nautobot-export-v1`): validates against its schema.
- Read-only token is role-managed (`nautobot_token_publish_openbao`, fail-closed
  non-superuser + view-only ObjectPermission + `write_enabled=False`).

## Roadmap — everything Nautobot can natively model

"Everything it is native for" is bounded by what Nautobot core + mature apps can
represent. Per-domain plan (no source-system changes — read-only ingestion only):

| Source domain | Native target | Mechanism | Status |
| --- | --- | --- | --- |
| DNS names | `IPAddress.dns_name` | extend the reservation/guest seed | tractable next |
| Physical devices/interfaces | DCIM Device/Interface | `nautobot-device-onboarding` (live discovery) | dry-run next |
| Cabling | DCIM Cable | onboarding / manual as-known | after onboarding |
| Firewall groups/rules, NAT/port-forwards | firewall models | `nautobot-firewall-models` app + SSoT job | needs app install |
| WLANs | Wireless models | Nautobot 2.x Wireless (Controller/RadioProfile/SSID) + SSoT | needs eval + SSoT |
| WAN circuits | Circuit / Provider | SSoT job | new SSoT job |
| Static/traffic routes | config-context / custom | design decision | design |
| VPN | L2VPN/tunnel or custom | design decision | design |
| RADIUS | Secrets / custom | design decision | design |
| Node storage / ingress | custom fields / config-context | design decision | design |

**Rule for every addition:** a new SSoT DataSource job per domain, run
`dryrun=True` first with the DiffSync diff reviewed before any committing run
(see the Phase-2 design §9). Add a mature app only where it demonstrably
increases read-only coverage; model with core first.

## What is NOT yet modeled (honest coverage gap)

Firewall, DNS records, WLANs, port profiles/forwards, static/traffic routes,
RADIUS, VPN, WAN, physical interfaces, and cables are **not yet in Nautobot** —
several require an app (firewall-models, wireless) or a modeling decision. The
repeatable drift report (`scripts/nautobot_drift.py`) lists this gap on every run
so it is never silently hidden.
