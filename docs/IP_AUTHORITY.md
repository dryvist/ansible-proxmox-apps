# IP Addressing Authority & DHCP-first Model

This document records **who owns addressing** across the homelab repos, the
**static-anchor policy** that decides which guests may keep a static IP, and the
**cross-repo work** required to move the remaining guests onto DHCP reservations
and, later, dual-stack IPv6.

It is the "why" behind [`/.claude/rules/ip-addressing.md`](../.claude/rules/ip-addressing.md)
(the "what": never hard-code an IP/port; consume from the source of truth).

## Why this exists

Terraform/OpenTofu can create a VM, but that does not make the platform safe to
build on. The goal is an **IPAM-driven, DHCP-first** foundation where addressing
intent lives in exactly one place, guests get their address by reservation
rather than a baked-in static IP, and downstream config **fails loud** when the
addressing authority is missing rather than silently wiring itself to a wrong or
loopback address. Concretely we want ~90% of guests to carry **no static IP** —
only a deterministic MAC and an FQDN — so that re-addressing (including the move
to IPv6) is a reservation change, not an edit sprawled across roles.

## Authority model — one owner per concern

| Concern | Authority | Notes |
| --- | --- | --- |
| DHCP + core networking (L2/L3, VLANs, gateway, reservations) | **UniFi** | Issues every DHCP reservation (MAC → IP); this repo never runs a DHCP server. |
| IPAM / DCIM source of truth | **Nautobot** (`roles/nautobot`, #138) | Staged SSoT DiffSync + export pipeline, currently gated off. |
| Provisioning + constants | **terraform-proxmox** (upstream) | Owns `deployment.json`; publishes `tofu_inventory.json` + `pipeline_constants` to S3. |
| Reservation seed (MAC → host) | **tofu-unifi** | `fixed-ips.json` — committed reservations, no literal IP (`cidrhost(cidr, host)`). |
| App configuration | **this repo** | **Read-only consumer**; reads the published inventory, never defines an IP/port, fails loud. |

The one-directional boundary matters: this repo consumes `tofu_data` and must not
reintroduce a value the upstream owns. Roles that need a value they cannot yet
read should fail, not fall back to a literal — a masking fallback produces a
role that "succeeds" while emitting broken config.

## The DHCP-first inventory contract

Every guest in `tofu_inventory.json` is described by three addressing fields
(see `tests/inventory_load/tofu_inventory.schema.json`):

| Field | Static anchor | DHCP-first guest |
| --- | --- | --- |
| `ip` | dotted IPv4 literal | an **FQDN** (DNS resolves it) |
| `mac` | `null` | deterministic locally-administered MAC (`02:` prefix) |
| `reserved_ip` | `null` | the UniFi DHCP **reservation** address (what DNS A records point at) |

`inventory/load_tofu.yml` surfaces `container_ip` (= `ip`) and
`container_reserved_ip` (= `reserved_ip`) as hostvars. Consumers that need a
literal address prefer `reserved_ip`, then `ip`, then the peer's
`container_ip` — and now stop there (no loopback tail). Consumers that can use a
name resolve the FQDN through Technitium/Traefik instead of any literal.

## Static-anchor policy

A guest may keep a **static IP only if it is a bootstrap anchor** — something the
rest of the fabric must reach before DNS/DHCP/IPAM is fully converged:

- **DNS / Technitium** — resolves everyone else; cannot depend on itself.
- **Proxmox hosts** — the hypervisors the `proxmox_pct_remote` connection dials.
- **Traefik / ingress VIP** — the ingress front door + its floating VIP.

**Everything else is DHCP-first**: no static IP, a deterministic MAC, a UniFi
reservation, and an FQDN. This is the rule to apply when adding or reviewing a
guest — if it is not one of the anchors above, it should have `mac` +
`reserved_ip` + an FQDN `ip`, not a static IPv4.

## Cross-repo instructions (work outside this repo)

The guest static→DHCP conversion and the constants this repo consumes live
upstream. Track them there:

### terraform-proxmox (`deployment.json` + constants)

1. **Convert non-anchor guests to DHCP-first**: for each guest that is not a
   static anchor, drop the static IPv4, and give it a deterministic `mac`, an
   FQDN, and a `reserved_host` so the export emits `reserved_ip`. Keep only the
   anchors static.
2. **Publish the missing constants** so this repo can drop the remaining port
   `default()` fallbacks (kept for now precisely because these are absent):
   `service_ports.{openbao_api, satellite_exporter, smokeping_prober,
   prometheus_web, blackbox_exporter, mssql}`, `ingress_ports.keepalived_vrid`,
   and the `syslog_port_map.{dns_query, macos}` families. Add each to
   `pipeline_constants`, `terragrunt apply`, then this repo removes the matching
   `| default(...)` and adds the constant to the CI fixture.

### tofu-unifi (`fixed-ips.json`)

- Add the MAC → host reservation for each newly DHCP-first guest.
- At the IPv6 phase, add dual-stack reservations (see roadmap below).

### homelab-contracts (`inventory_resolve` role + schema)

- Mirror any `tofu_inventory.schema.json` change here into the shared contract
  and the `inventory_resolve` output shape (this repo installs it via
  `requirements.yml`; CI installs it in `_data-contract.yml`).

### Nautobot cutover

- Sequenced separately in [`roles/nautobot/README.md`](../roles/nautobot/README.md).
  Seed + export are safe to run as an observed shadow SSoT; the authority-flip
  (terraform deriving `tofu_inventory.json` **from** Nautobot) stays an
  operator-gated step.

## IPv6 roadmap (planned; not yet code)

The contract is IPv4-only today. When upstream begins assigning v6, land these
**additively** (a guest resolvable by FQDN is already v4/v6-transparent, so
name-based consumers need no change):

1. **Schema** — widen `container_entry.reserved_ip` and the `ip`/`vm` entries in
   `tests/inventory_load/tofu_inventory.schema.json` to accept an IPv6 literal
   (an `anyOf` branch alongside IPv4/hostname). `mac` is address-family neutral —
   no change. Static anchors (e.g. `splunk`) may stay IPv4-only.
2. **Technitium** — emit `AAAA` for a `reserved_ip` that is an IPv6 literal:
   tag each record `A`/`AAAA` by family in the builder, relax the "must be IPv4"
   assertion to "must be IPv4 **or** IPv6" (still fail on a bare FQDN = a
   DHCP-first guest missing its reservation), and extend the retired-record
   prune to enumerate `AAAA` as well as `A`
   (`roles/technitium_dns/tasks/main.yml`).
3. **Nautobot** — bump the export contract to `v1.1.0` with additive v4-or-v6
   patterns, and derive the SSoT `mask_length` from the address family
   (v4→32, v6→128) instead of a hard-coded `/32`
   (`ssot_ip_addresses.py`, `ssot_virtualization.py`).
4. **CI** — add a dual-stack fixture guest to `tofu_inventory.json` and an
   assertion in `verify_inventory.yml` so the v6 branch is exercised.

## Golden rule

Per `/.claude/rules/ip-addressing.md`: **document how to retrieve a value, never
the value itself.** This file names mechanisms, fields, and constant *keys* — not
IPs, subnets, or port numbers.
