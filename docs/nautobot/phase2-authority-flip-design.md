# Phase 2 — Nautobot Authority-Flip Design

Status: **DESIGN ONLY — do not execute.** This document is Phase 1 exit
criterion 5 (the written authority-flip design) for the Nautobot
source-of-truth effort tracked in
[dryvist/ansible-proxmox-apps#977](https://github.com/dryvist/ansible-proxmox-apps/issues/977).
Phase 2 is a separate, separately-gated engagement; nothing here is a licence to
begin the flip.

## 1. Phase boundary

- **Phase 1 (absorb):** Nautobot learns everything, writing to nothing but its
  own DB and reviewed PRs. Its consumption contracts (GraphQL dynamic inventory,
  `nautobot-export-v1` artifact) are proven *ready* but not cut over.
- **Phase 2 (own — this doc's subject):** authority for each network-intent
  field moves to Nautobot; the execution planes (DNS, DHCP, the network
  controller) reconcile *from* Nautobot instead of being hand-fed; OpenTofu
  keeps guest lifecycle only.

The invariant that separates them: **Phase 1 never becomes the writer.** The
first write of authority is the first act of Phase 2.

## 2. Current state (verified, Phase-1 recon)

Who writes each fact today:

| Fact | Today's writer | Today's consumers |
| --- | --- | --- |
| Guest lifecycle (vmid, node, cpu, mem, disk, template, features, pool, tags) | `tofu-proxmox` `deployment.json` | `ansible_inventory.json` → Ansible repos |
| Guest IP / MAC / gateway / reserved-IP | `tofu-proxmox` (derived from VLAN+vmid; deterministic MAC) | inventory artifact; controller reads back MAC+IP |
| VLAN → subnet table (`network_cidrs`) | `tofu-proxmox` `deployment.json` | IP derivation above |
| Network defs, reservations, firewall, DNS, WLAN, routes, VPN, WAN, device | network-controller (UniFi) IaC | controller; reservations feed inventory |
| DNS A records | `technitium_dns` role, pointed at reserved IP | clients |
| Ansible host/group membership | `ansible_inventory.json` + `load_tofu.yml` tags | every playbook |

What Nautobot already models (Phase-1 seed pipeline, **gated off by default**,
activated only at cutover via `nautobot_build_seed` + `nautobot_run_seed_jobs`):
VLANs, Prefixes, IPAddresses (from the reservation feed), Racks + rack Devices +
BMC interfaces, Proxmox nodes as Devices, guests as VirtualMachines with a
primary IP. It does **not** yet model: guest Tags (so tag→group inventory is
inert — see #1008), Cables, physical interface↔IP bindings, or live-discovered
network devices.

**Model-coverage reality:** only four source domains map to Nautobot *core*
models — networks→VLAN+Prefix, reservations→IPAddress, adopted device→Device,
DNS-name→`IPAddress.dns_name`. Firewall groups/rules and NAT need a plugin
(e.g. nautobot-firewall-models); WLANs, port-profiles, static/traffic routes,
VPN, WAN, and RADIUS have no core model and require custom models or
config-contexts. This bounds what "Nautobot owns network intent" can mean at
flip time and is the largest open prerequisite (§7).

## 3. One-writer-per-field ownership map (Phase 2 target)

The rule: exactly one system is the **writer** of each field; every other system
is a **reader** that reconciles from it. No field has two writers; no
bidirectional sync.

| Field / domain | Phase-2 writer | Readers (reconcile FROM writer) |
| --- | --- | --- |
| VLAN id/name, subnet/prefix, VLAN→CIDR map | **Nautobot** (VLAN, Prefix) | tofu-proxmox (IP math), controller, Ansible |
| Host IP address, prefix, gateway | **Nautobot** (IPAddress, Prefix) | Ansible inventory, DNS, DHCP |
| Fixed-IP / DHCP reservation (MAC↔IP) | **Nautobot** (IPAddress + iface/MAC) | controller IaC (DHCP), tofu-proxmox (reads assigned IP) |
| DNS name (A/PTR intent) | **Nautobot** (`IPAddress.dns_name`) | `technitium_dns` role reconciles records |
| Firewall groups/rules, NAT/port-forwards | **Nautobot** (firewall plugin) — *pending model* | controller IaC renders rules |
| WLAN, port-profile, routes, VPN, WAN, RADIUS | **Nautobot** (custom/config-context) — *pending model* | controller IaC |
| Ansible host/group membership | **Nautobot** (tags + GraphQL inventory) | every playbook |
| Guest lifecycle (cpu, mem, disk, template, features, pool…; full list §4) | **OpenTofu** (`deployment.json`) | Proxmox, inventory |
| Physical: rack, device, interface, cable | **Nautobot** (DCIM; onboarding-discovered) | as-built docs, export |
| Deterministic MAC | **OpenTofu** at create → published to Nautobot as the iface MAC (then authoritative) | controller IaC DHCP |

Boundary line: **Nautobot owns "where it lives on the network" (IPAM / DNS /
VLAN / firewall intent); OpenTofu owns "what the guest is" (lifecycle).** The MAC
is the one hand-off: OpenTofu still mints the deterministic MAC when it creates
the guest NIC, but writes it *into* Nautobot, which becomes the single reader
surface for the controller's DHCP reservations.

## 4. `deployment.json` shrink plan

`deployment.json` (schema `deployment.schema.json`) shrinks to guest-lifecycle
only. The publish boundary is `tofu apply` writing `ansible_inventory.json`
(single S3 object; the `lifecycle.precondition` blocks are the schema gate).

**Stays (guest lifecycle):** `vm_id`, `hostname`, `node_name`, `cpu_cores`,
`memory_dedicated`/`memory_swap`, `root_disk`, `mount_points[]`,
`device_passthrough[]`, `template`/`os_type`, `unprivileged`, `protection`,
`features`, `tags`, `pool_id`, `start_on_boot`, `user_account`, and the
top-level `nodes`, `node_storage`, `pools`, `datastores`, `host_services`,
`proxmox_node`, `vm_ssh_public_key`.

**Leaves (moves to Nautobot authority):** `vlan`, `network_cidrs`, `ip_config`
(`ipv4_address`/`ipv4_gateway`), `dhcp`, `reserved_host`, `network_interfaces[]`,
`domain`; and the `modules/proxmox-stack/locals.tf` derivation block
(`container_address`, `container_mac`, `container_gateway`,
`container_reserved_ip`, and the VM equivalents) is deleted or repointed to read
Nautobot.

Migration order matters: **Nautobot must be authoritative and populated for the
guest's IP/VLAN before the field is removed from `deployment.json`**, or the
`cidrhost` derivation loses its input and DHCP reservations go stale. Populate
Nautobot (Phase 1) → repoint the derivation to read Nautobot (Phase 2 step) →
only then delete the source fields (schema bump).

## 5. `ansible_inventory.json` retirement path

The artifact is `schema_version 2.0.0`, keys `containers`/`vms`/`docker_vms`/
`splunk_vm`/`constants`/`ingress`/`ingress_vip`/`ingress_hosts`/`host_services`/
`nodes`/`node_storage`/`domain`, written to the RustFS `iac-inventory` bucket.
Five consumers: `ansible-proxmox`, `ansible-proxmox-apps` (`load_tofu.yml`),
`ansible-splunk`, the controller IaC (reads MAC + reserved IP), and the
`technitium_dns` role.

Retirement is a **`schema_version 3.0.0` breaking bump**, done in two options
(prefer **A** first, then **B** once all readers are proven on Nautobot):

- **Option A — strip network fields, keep the shim.** Remove per-guest `ip`,
  `mac`, `reserved_ip` (and `ingress*`) from the published artifact;
  consumers pull addressing from Nautobot's dynamic inventory. Guest-lifecycle
  keys (`vmid`, `node`, `ansible_connection`, `ansible_pct_vmid`, `tags`,
  `pool_id`, `constants`) stay OpenTofu-sourced — those never live in Nautobot.
  **`domain` also stays in the shim.** `inventory/load_tofu.yml` asserts
  `tofu_data.domain` is defined and non-empty (the "carries the node-FQDN
  derivation inputs" gate) and derives every LXC `ansible_host` as
  `{node-role}.{domain}`; stripping `domain` breaks the loader before any reader
  reaches Nautobot. It leaves only once `load_tofu.yml` itself is retired
  (Option B).
- **Option B — full retire.** Delete `aws_s3_object.ansible_inventory` and the
  `iac-inventory/ansible_inventory.json` key; repoint all five consumers at
  Nautobot. Only reachable after every consumer runs green on Option A.

The artifact ends Phase 2 as a legacy shim (Option A) or gone (Option B),
matching the #977 "done when" state.

## 6. Per-repo change lists

- **tofu-proxmox** — shrink `deployment.schema.json` + `variables-containers.tf`
  to the lifecycle field set; delete/repoint the `locals.tf` network-derivation
  block; bump the published artifact to `3.0.0` (Option A: strip network fields).
- **ansible-proxmox-apps (this repo)** — flip `ansible.cfg` inventory to
  `inventory/nautobot.yml`; close the parity gap first (add `postgres_ai_group`,
  `ai_orchestration_group`, `authelia_group` — the exact `_group`-suffixed names
  `load_tofu.yml` emits — or confirm they moved to
  `ansible-proxmox-ai`); land #1006 (role-managed read-only token) and #1008
  (tag sync) so the GraphQL inventory is trustworthy; retire the `load_tofu.yml`
  network-field dependence.
- **ansible-proxmox** — repoint host sourcing from the artifact to Nautobot.
- **ansible-splunk** — `splunk_vm` + `constants` still come from the artifact
  (lifecycle/constants), so it is affected only by Option B; verify no network
  field is read.
- **the network-controller (UniFi) IaC** — flip DHCP-reservation rendering,
  firewall/DNS/WLAN/route intent to read from Nautobot instead of its own JSON;
  this is the largest reader change and is gated on the Nautobot model coverage
  in §7.
- **technitium_dns role** — source A/PTR records from `IPAddress.dns_name`
  instead of the artifact's reserved IP. **Gap:** the GraphQL dynamic-inventory
  query in `inventory/nautobot.yml` fetches only `name`, `primary_ip4.host`, and
  `tags` — not `dns_name` — and the role today keys on
  `hostvars[item].hostname`. The query must add `dns_name` and the role repoint
  to it before this reader can flip.

## 7. Prerequisites & open questions (must close before flip)

1. **Model gap.** Firewall/NAT need a plugin; WLAN/routes/VPN/WAN/RADIUS/
   port-profiles need custom models or config-contexts. Until modeled, those
   domains cannot flip and the controller IaC stays their writer. Decide
   per-domain: model it, or explicitly keep it OpenTofu-owned and out of scope.
2. **#1006 / #1008** must be merged and converged — a role-managed read-only
   token and guest-tag sync — or the GraphQL inventory cannot answer with 1:1
   group parity.
3. **Export contract asymmetry.** VirtualMachines are seeded in but absent from
   `nautobot-export-v1`; decide whether the export must round-trip guests before
   it is a retirement-grade artifact.
4. **Reservation circular dependency.** Today tofu-proxmox computes the IP and
   the controller reads it back. Post-flip both read Nautobot; sequence the
   repoint so neither is briefly the writer of a field the other also writes.

## 8. Rollback

Each step is independently reversible because Phase 1 leaves the artifact intact:

- **Inventory cutover** (`ansible.cfg` → `nautobot.yml`): revert the one-line
  config change; `load_tofu.yml` + the still-published artifact resume sourcing.
- **`deployment.json` shrink**: the removed fields live in git history and the
  `2.0.0` artifact; restore the schema + `locals.tf` block and re-apply to
  republish network fields. Do **not** delete the `2.0.0` publish path until
  every consumer is proven on `3.0.0`.
- **Controller reader flip**: revert to reading its own desired-state JSON; the
  JSON is unchanged in Phase 2 (Nautobot became authoritative *of the same
  values*, not a new source of truth), so a revert is loss-free.

Rollback invariant: **keep the old writer's data intact and the old artifact
published until the new reader path is proven green**, so any step reverts to a
known-good source with no data reconstruction.

## 9. Phase-2 safety gates (from adversarial review)

These gates were surfaced by an independent review and must be satisfied before
authority flips — schema validity and additive absorption are necessary but not
sufficient.

- **Semantic validation, not just schema.** A schema-valid export can still
  carry duplicate IP allocations, overlapping subnets, duplicate MACs, or
  unresolvable FQDNs. Before Phase 2 applies Nautobot data, run pre-flight checks
  for IP collisions, subnet overlap, duplicate MAC, and FQDN resolvability. A
  schema pass alone must not gate the flip.
- **Drift triage before absorption.** Classify every drift item before it enters
  Nautobot: IaC-managed (stale seed — safe to absorb), ephemeral/test, or
  genuinely out-of-band (created outside IaC). Absorbing an out-of-band object
  makes it authoritative with no OpenTofu state behind it — a Phase-2 trap where
  the controller has no HCL/state and may conflict or re-create. Only IaC-sourced
  facts absorb silently; others are classified or fixed upstream first.
- **Explicit DiffSync diff, reviewed before commit.** The seed runner commits
  directly (`dryrun=False`). Phase-2-grade absorption should first run the SSoT
  jobs in `dryrun=True`, capture the create/update/delete DiffSync diff, and
  review it before the committing run — the drift report is a proxy, not the
  native diff.
- **Deletion-safety cap.** Additive models make delete a no-op today; if any
  future sync enables deletion, gate it on a threshold (e.g. abort if >5% of a
  model's objects would be deleted) so a bad source never mass-deletes.
- **No boot-loop dependency.** Nautobot must never become a boot prerequisite for
  the execution planes: if it is down or state-lost, DNS/DHCP/controllers and
  OpenTofu must still boot and be able to reconstruct Nautobot — not deadlock
  waiting on it. Audit the recovery order before the flip.
