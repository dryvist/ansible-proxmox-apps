# node_exporter

Install [prometheus node_exporter](https://github.com/prometheus/node_exporter)
on every guest (LXC + VM) in this repo's inventory as a pinned-version native
systemd service, exposing host metrics (CPU, memory, disk, network) on port
`9100`.

This is the guest-level equivalent of the sibling `ansible-proxmox` repo's
`pve_node_exporter` role, which covers the PVE hosts themselves — that repo
owns PVE-node-level roles, this one owns guest-level roles. The two roles are
deliberately separate (different repos, different host groups) rather than a
shared collection.

## What It Does

1. Creates a dedicated no-login system user (`node-exporter`).
2. Downloads the **pinned** upstream release tarball to a versioned path under
   `/opt/node_exporter/` (skipped when already present; optional sha256 pin).
3. Unpacks it (versioned, `creates:`-guarded) and installs the binary to
   `/usr/local/bin/node_exporter` — only rewritten on a version bump.
4. Optionally creates the textfile-collector directory so scripts can publish
   custom metrics by dropping `*.prom` files.
5. Deploys a hardened systemd unit and enables/starts the service.

Re-runs are no-ops; bumping `node_exporter_version` (plus checksum) rolls the
fleet forward on the next converge. No container-vs-host branching is needed:
unlike a clock daemon, node_exporter only reads `/proc`/`/sys` and needs no
privilege an unprivileged LXC lacks, so the same unit runs identically on
every guest.

## Installation

No collection dependency: every task uses `ansible.builtin` modules. Consumed
as an ordinary role dependency from `playbooks/site.yml`; nothing to install
separately.

## Where It Runs

Wired into `playbooks/site.yml` against every guest (`hosts: all:!localhost`).
By default the exporter binds the guest's **management IP** (the default-route
interface fact, derived at runtime — never hardcoded), so metrics are only
reachable on the management VLAN.

## Usage

Runs with the rest of `site.yml`, or target just this role by tag:

```bash
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --limit all,localhost --tags node_exporter
```

### Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `node_exporter_version` | `1.9.1` | Pinned upstream release. |
| `node_exporter_download_url` | GitHub releases URL | Override to a local mirror if guests must not reach the internet at converge time. |
| `node_exporter_checksum` | pinned per-arch sha256 | Optional `sha256:<hex>` pin for the tarball. Empty skips the check. |
| `node_exporter_listen_address` | guest's mgmt IP (`ansible_default_ipv4.address`) | Bind address; set `0.0.0.0` for all interfaces. |
| `node_exporter_port` | `9100` | Listen port. |
| `node_exporter_user` | `node-exporter` | Service account. |
| `node_exporter_install_dir` | `/opt/node_exporter` | Versioned install root. |
| `node_exporter_textfile_collector_enabled` | `true` | Enable the textfile collector. |
| `node_exporter_textfile_collector_dir` | `/var/lib/node_exporter/textfile_collector` | Drop `*.prom` files here to expose custom metrics. |
| `node_exporter_extra_args` | `[]` | Extra CLI flags appended to `ExecStart`. |

## Verification

```bash
systemctl is-active node_exporter
curl -s http://<guest-mgmt-ip>:9100/metrics | head

# Version actually running matches the pin
/usr/local/bin/node_exporter --version
```

## License

Apache-2.0, matching the repository (node_exporter itself is Apache-2.0).
