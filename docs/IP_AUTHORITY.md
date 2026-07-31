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
| Provisioning + constants | **tofu-proxmox** (upstream) | Owns `deployment.json`; publishes `tofu_inventory.json` + `pipeline_constants` to S3. |
| Reservation seed (MAC → host) | **tofu-unifi** | `fixed-ips.json` — committed reservations, no literal IP (`cidrhost(cidr, host)`). |
| App configuration | **this repo** | **Read-only consumer**; reads the published inventory, never defines an IP/port, fails loud. |

The one-directional boundary matters: this repo consumes `tofu_data` and must not
reintroduce a value the upstream owns. Roles that need a value they cannot yet
read should fail, not fall back to a literal — a masking fallback produces a
role that "succeeds" while emitting broken config.

## The DHCP-first inventory contract

Every guest in `tofu_inventory.json` is described by **two** addressing fields
(see `tests/inventory_load/tofu_inventory.schema.json`):

| Field | Network / critical guest | Leased guest |
| --- | --- | --- |
| `ip` | dotted IPv4 literal (declared once, upstream) | an **FQDN** (DNS resolves it) |
| `mac` | `null` | deterministic locally-administered MAC (`02:` prefix) |

`inventory/load_tofu.yml` surfaces exactly one address fact per guest,
`container_ip` (= `ip`). There is deliberately no second, address-shaped fact
beside it.

> **`reserved_ip` is gone and must not come back.** It carried the address a
> leased guest was supposed to be given, which meant that address was written
> down in three places — the IaC repo, the controller's DHCP reservation, and
> the published DNS record — with nothing keeping them in agreement. They drifted
> repeatedly. It also cost nothing to remove: the gateway answers DNS for the
> clients in its own lease table, so a leased guest resolves by name whether or
> not a reservation exists.
>
> Every consumer that read it had also grown its own copy of the same "prefer the
> reservation, else the name" branch. Deleting the field deleted eight of those.

The `mac` stays, for a reason that is not addressing: **lease stability**. A
stable MAC means a rebuilt guest renews the same lease, so it keeps its address
and its lease-table name.

## Consumers use FQDNs, full stop

App configuration references services **by name, never by address**:

- **Traefik-fronted service** (has a row in the upstream ingress table):
  `https://<name>.{{ tofu_data.domain }}` — port 443, TLS via the wildcard
  cert. The name resolves to the ingress; the backend address is Traefik's
  concern, not the consumer's.
- **Non-fronted guest**: `<hostname>.{{ tofu_data.domain }}` plus the port
  from `tofu_data.constants`. For a network/critical guest that name is an A
  record Technitium builds from the inventory; for a leased guest it is answered
  by the gateway out of its own DHCP lease table. The consumer cannot tell the
  difference, which is the point.
- `{{ tofu_data.domain }}` is the **single domain source of truth**
  (published by tofu-proxmox, validated non-empty by
  `inventory/load_tofu.yml`). Never repeat a literal domain per role.
- Hostnames **match the app/role/stanza name**. Never invent a third name.

The bring-up order guarantees names work before any role converges. For a
leased guest it is now two steps shorter, because there is nothing to reserve
and nothing to publish: IaC creates the guest (deterministic MAC) → it takes a
lease → the gateway answers its name → the role converges by FQDN. A
network/critical guest instead declares its address in IaC, and Technitium
publishes the record.

### Where IP-valued variables are still legitimate

1. **`roles/technitium_dns`** — builds the A records themselves. It publishes a
   record only for a guest that DECLARES an address, i.e. the network/critical
   tier. Leased guests are skipped on purpose: the lease table already answers
   for them, and a record here would be a second copy of an address nothing
   reconciles.
2. **The IPAM tier** (`roles/nautobot` seed prefixes/CIDRs) — IPAM stores
   addresses by definition. A leased guest is recorded as `dhcp` with no
   address, which is the honest record rather than an invented one.
3. **Roles that run from behind the VPN tunnel** (`download_vpn`,
   `servarr_wiring`, `configarr`, `sortarr`) — documented exception: that guest
   resolves through Proton DNS and genuinely cannot resolve internal FQDNs, so
   it needs an address. That address is **discovered** from the target guest's
   own interface (`ansible_default_ipv4`), never declared anywhere, so it cannot
   go stale and needs no re-apply after a re-IP. Narrows further once split-DNS
   lands inside that container (#870).

Anything else that dereferences `container_ip` / `tofu_data.containers[*].ip`
for an ADDRESS (rather than passing it through as a name) is a defect to
migrate — tracked in #871. Name-based SMTP for the Traefik-fronted mailpit
is #872.

## Static-anchor policy

A guest may keep a **static IP only if it is network- or critical-tier** —
something the rest of the fabric must reach before DNS/DHCP is converged, or
that so much points at that an address change would force a fleet-wide
re-converge:

- **DNS / Technitium** — resolves everyone else; cannot depend on itself.
- **Proxmox hosts** — the hypervisors the `proxmox_pct_remote` connection dials.
- **Traefik / ingress VIP** — the ingress front door + its floating VIP.
- **HAProxy, OpenBao, Cribl Stream, agentgateway** — every guest resolves
  credentials, ships logs, or routes through these.

Their address is declared **once**, upstream, and nothing mirrors it.

**Everything else is DHCP-first**: no static IP, no declared octet, no
reservation — a deterministic MAC and an FQDN, and that is all. This is the rule
to apply when adding or reviewing a guest. If it is not in the list above, it
should have `mac` + an FQDN `ip` and nothing else about its address.

## Cross-repo instructions (work outside this repo)

The guest static→DHCP conversion and the constants this repo consumes live
upstream. Track them there:

### tofu-proxmox (`deployment.json` + constants)

1. **Convert non-anchor guests to DHCP-first**: for each guest that is not
   network- or critical-tier, drop the static IPv4 and set `dhcp: true`. That is
   the whole change — there is no octet to pick and no reservation to add. App
   configs in this repo are unaffected: they reference the FQDN.

### tofu-unifi (`fixed-ips.json`)

- **Do not add a reservation for a leased guest.** Reservations remain only for
  physical infrastructure (nodes, BMCs), which is genuinely static kit. A
  reservation mirroring an IaC-managed guest is a second copy of its address.
- Retire any reservation that mirrors a guest converted to DHCP-first.

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

1. **Schema** — widen the `ip`/`vm` entries in
   `tests/inventory_load/tofu_inventory.schema.json` to accept an IPv6 literal
   (an `anyOf` branch alongside IPv4/hostname). `mac` is address-family neutral —
   no change. Static anchors (e.g. `splunk`) may stay IPv4-only.
2. **Technitium** — emit `AAAA` for an `ip` that is an IPv6 literal: tag each
   record `A`/`AAAA` by family in the builder, widen the builder's
   address-shaped filter and the "must be IPv4" assertion to accept either
   family (a bare FQDN still means a leased guest, which is skipped), and extend
   the retired-record prune to enumerate `AAAA` as well as `A`
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
