# nautobot

Deploys **Nautobot** as the homelab's IPAM/DCIM **source of truth** (issue #138):
a native install plus the SSoT DiffSync jobs that seed it from the hand-maintained
upstream sources, and an export Job that publishes the inventory artifact to S3.

Nautobot is the IPAM authority in the [addressing model](../../docs/IP_AUTHORITY.md);
**UniFi remains the DHCP + core-networking authority** and **tofu-proxmox
remains the provisioning + constants authority**. This role never runs a DHCP
server and never re-defines an upstream-owned value.

## Installation

Wired into `playbooks/site.yml` against any host in `nautobot_group`. The group
is populated by `inventory/load_tofu.yml` from `containers` tagged `nautobot` in
the OpenTofu inventory, reached over `proxmox_pct_remote`.

Prerequisites:

- The `nautobot` LXC exists (OpenTofu-managed; tags include `container`,
  `nautobot`).
- A reachable PostgreSQL primary, plus the SECRET_KEY and superuser password as
  environment variables. However you manage that is an implementation detail —
  the role reads plain environment variables, so anything that sets them works.

Install the collection dependencies once:

```sh
ansible-galaxy collection install -r requirements.yml
```

## Usage

Converge the role:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags nautobot --limit nautobot_group,localhost
```

Build a seed bundle without writing to the database, then inspect it:

```sh
ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags nautobot --limit nautobot_group,localhost \
  -e nautobot_build_seed=true
```

Verify seed assembly offline, with no guest involved:

```sh
ansible-playbook tests/nautobot_seed/verify_seed_bundle.yml -c local
```

See the flag ladder below before enabling anything that writes.

## Two layers

`tasks/main.yml` splits into:

- **Deterministic layer (always on):** system deps, user, Redis on loopback,
  SECRET_KEY, rendered config/env/uWSGI, jobs + contract copied into place,
  systemd units. Idempotent, no live-DB writes. This is what Molecule validates
  (with `nautobot_manage_app: false`).
- **Live layer (`when: nautobot_manage_app`):** venv + pip install, migrate,
  collectstatic, superuser, service start, export/discovery schedules, health
  check, and — only when gated on — the one-shot seed run.

## Flag ladder

Enabling flags is **ordered**: `manage_app` → `build_seed` → `run_seed_jobs` →
`run_export`. Seed and export are safe to run as an **observed shadow SSoT**; no
flag here flips authority.

| Flag | Default | What it does | Enable when |
| --- | --- | --- | --- |
| `nautobot_manage_app` | `true` | Runs the live layer (install/migrate/services). | Production path (default). |
| `nautobot_build_seed` | `false` | Assembles `nautobot_seed.json` — a file only, no DB write. | Cutover, via `-e`. |
| `nautobot_run_seed_jobs` | `false` | DiffSyncs the seed into live Nautobot (additive). | Cutover, after the seed. |
| `nautobot_run_export` | `false` | One-shot publish of the export during the converge. | Optional. |
| `nautobot_run_discovery` | `false` | SSH-CLI device onboarding (netmiko). | Optional; out of scope. |

Caveats:

- **`manage_app`** — idempotent; Molecule pins it `false` to skip the multi-minute install and live DB.
- **`build_seed`** — every source is independent, so any subset builds a valid
  bundle covering just those slices; the run fails only when no source at all is
  available. The tofu inventory is resolved on every run, so a seed carrying the
  guest slice alone needs nothing extra on the controller. Never enable in
  Molecule (it stamps `generated_at`, breaking idempotence) —
  `tests/nautobot_seed/verify_seed_bundle.yml` covers assembly instead.
- **`run_seed_jobs`** — every model's `delete()` is a no-op, so re-runs are safe and cannot delete another owner's objects; an empty bundle is a no-op.
- **`run_export`** — only meaningful with `run_seed_jobs`; steady-state publishing already runs daily via the beat schedule.
- **`run_discovery`** — inert unless `NAUTOBOT_ONBOARD_TARGETS` is set; native-API discovery of Proxmox/iDRAC/UniFi is a tracked follow-up.

**Publish safety:** the export writes a **separate S3 key**
(`nautobot/nautobot_export.json`) — distinct from terraform's authoritative
`ansible_inventory.json`. No consumer reads it as source, so it stays a shadow
until the authority-flip. If the export bucket is unset the upload fails closed
(nothing is published).

## Ingress catalog boundary

The published OpenTofu ingress table is the current writer for UI hostname,
path, backend, and SSO metadata. It supports a shared hostname with a
path-specific API or webhook route, which lets browser UIs be SSO-gated without
breaking machine clients. A future Nautobot Config Context mirror may validate
this catalog, but it must remain additive and non-boot-critical until the
separate authority-flip gates are complete.

## Prefix roles and `dhcp-pool`

`tasks/seed_bundle.yml` builds Nautobot prefixes from `NAUTOBOT_SEED_NETWORKS`
(a list of `{vid, name, cidr, role?}`). Each network's prefix `role` now comes
from an **optional per-network `role`**, defaulting to the VLAN `name`:

```jmespath
{prefix: cidr, vlan_vid: vid, role: role || name}
```

This lets a scope be modelled as a first-class **`dhcp-pool`** prefix (or any
free-form role) without inventing a VLAN by that name — e.g. a
`{vid: 20, name: "servers", cidr: "…", role: "dhcp-pool"}` entry, or a standalone
pool prefix. Downstream (`ssot_vlans_prefixes.py`, `export_nautobot.py`) and the
export contract already accept any free-form role, so no other change is needed.
IPv6 prefixes seed with no code change once a v6 CIDR is present in
`NAUTOBOT_SEED_NETWORKS` (see the [IPv6 roadmap](../../docs/IP_AUTHORITY.md#ipv6-roadmap-planned-not-yet-code)).

## Go-live runbook (operator-gated)

All runtime gates ship `false`/`true` at their safe defaults above; advance the
cutover deliberately:

1. Place whichever sibling-repo sources you have on the controller and export
   their paths + `NAUTOBOT_SEED_NETWORKS` (now optionally carrying
   `role: dhcp-pool` and, later, v6 CIDRs) + `NAUTOBOT_EXPORT_S3_BUCKET`. None
   of these is required on its own: the resolved tofu inventory always supplies
   the guest slice, and each absent source just contributes nothing.
2. `… site.yml -t nautobot -e nautobot_build_seed=true` → writes
   `nautobot_seed.json` only. **Inspect it.**
3. Re-run with `-e nautobot_build_seed=true -e nautobot_run_seed_jobs=true` →
   additive DiffSync populates live Nautobot. Re-runnable safely.
4. Optionally `-e nautobot_run_export=true` for an immediate publish; otherwise
   the daily beat schedule publishes.
5. **Observe** the shadow `nautobot_export.json` for one or more cycles.
6. The **authority-flip** — tofu-proxmox deriving `tofu_inventory.json`
   *from* Nautobot instead of `deployment.json` — is a separate, upstream,
   operator-approved step. It also requires the export contract to first grow to
   a superset of the inventory (`vmid`, `node`, `tags`, ports, static-vs-reserved
   distinction). Never a default here.

See [`docs/IP_AUTHORITY.md`](../../docs/IP_AUTHORITY.md) for the full authority
model, the static-anchor policy, and the cross-repo instructions.
