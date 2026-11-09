# syslog_forwarder

Forward an infra LXC's logs to the central syslog pipeline so everything lands
in Splunk. Installs `rsyslog`, which ingests the systemd journal by default on
Debian, and adds one drop-in rule that ships **all** logs to the HAProxy syslog
VIP.

```text
this LXC (journald + rsyslog)
  -> syslog.<PROXMOX_SUBDOMAIN>:<linux port>  (TCP, disk-assisted queue)
     -> HAProxy syslog VIP
        -> Cribl Edge  (syslog pipeline)
           -> Splunk HEC  (os index)
```

## How it works

`rsyslog` reads the systemd journal (`imjournal`) by default on Debian, so a
single forward rule captures host logs plus every native systemd service. The
rule uses `omfwd` with a disk-assisted action queue that buffers up to
`syslog_forwarder_queue_max_disk_space`; if full, enqueue can time out. TCP
keepalive detects stale idle connections so forwarding can resume after the
receiver returns.

Debian's `rsyslog.service` ships systemd sandboxing (`PrivateDevices`,
`ProtectKernelTunables`, `ProtectControlGroups`, …) that an unprivileged LXC
cannot satisfy — systemd fails the unit with `status=226/NAMESPACE` before
`rsyslogd` runs. The role drops in
`/etc/systemd/system/rsyslog.service.d/zz-lxc-unpriv.conf` to neutralize those
directives so the forwarder starts in a container. It disables only the
host-privilege sandboxing, not any rsyslog functionality.

Where `syslog_forwarder_limit_nofile` is set, the role also drops in
`zz-limits.conf` beside it to raise the unit's `LimitNOFILE`: imfile holds one
open descriptor for every file a wildcard input matches, so a host tailing an
accumulating wildcard (GitHub runner `_diag` logs) needs headroom past the
1024 default. Unset, the drop-in deploys nowhere and the unit is unchanged.

## What it captures

- All host/system logs and **every native systemd service** (Traefik,
  Technitium, apt-cacher-ng, etc.) — these go through journald, which rsyslog
  reads.
- **Docker-in-LXC container logs** only when that service's Compose `logging`
  driver is `journald` (set per service in the relevant `*_docker` role). The
  default Docker `json-file` driver is **not** in journald and is not forwarded.

## Where it runs

Applied by the `site.yml` play to `lxc_containers` **minus** the pipeline and
load balancer:

```text
lxc_containers:!cribl_edge:!cribl_stream_group:!haproxy_group
```

Those hosts are excluded to avoid forwarding into the receiver they feed. Their
own logs are better collected locally by Cribl Edge (a separate follow-up).

## Installation

No manual install. The role is wired into `playbooks/site.yml` and runs against
the host pattern above on every converge. `rsyslog` is installed by the role via
`apt`. Ansible collection dependencies come from the repo `requirements.yml`.

## Usage

Deploy with the rest of the apps, or target just this role by tag:

```bash
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags syslog_forwarder
```

### Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `syslog_forwarder_target_host` | `syslog.{{ PROXMOX_SUBDOMAIN }}` | The `syslog` CNAME (→ HAProxy VIP). Never a literal. |
| `syslog_forwarder_target_port` | `tofu_data.constants.syslog_ports.linux` | Linux syslog port (→ Splunk `os` index). |
| `syslog_forwarder_protocol` | `tcp` | `tcp` (reliable) or `udp`. |
| `syslog_forwarder_queue_max_disk_space` | `256m` | Disk-queue cap during a receiver outage. |
| `syslog_forwarder_keepalive` | `on` | Enables TCP keepalive for both forwarding actions. |
| `syslog_forwarder_keepalive_time` | `120` | Idle seconds before the first keepalive probe. |
| `syslog_forwarder_keepalive_interval` | `30` | Seconds between unanswered keepalive probes. |
| `syslog_forwarder_keepalive_probes` | `3` | Unanswered probes before the connection is declared dead. |
| `syslog_forwarder_imfile_inputs` | `[]` | File-only loggers to tail via imfile: `file`, `tag` (→ `$programname`), optional imfile params (below). |
| `syslog_forwarder_limit_nofile` | unset | systemd `LimitNOFILE` for `rsyslog.service`, rendered as a drop-in only where set. |

Port and target are sourced from the inventory / `PROXMOX_SUBDOMAIN`, never
hardcoded (see `.claude/rules/ip-addressing.md`).

### Optional imfile input parameters

An input entry may carry any imfile input parameter as an extra key. It renders
quoted, and only when set — `file` and `tag` render positionally and the
ruleset stays the default ruleset, so an entry without extra keys renders
exactly as before. Quoted numbers are fine (rsyslog coerces them), and the
deploy validates the rendered drop-in with `rsyslogd -N1`.

`closeTimeout` (seconds) is the wildcard-relevant one: in inotify mode, imfile
closes a file once it has had no new data for that long, instead of holding an
open descriptor for every file the glob matches. Check the target hosts'
rsyslog version before reaching for it — 8.2302.0 (Debian bookworm) does not
know the parameter, and the deploy's `rsyslogd -N1` validation fails the play
when an input sets it. Where writers never append to old files and the
rsyslog version rejects `closeTimeout`, raise the unit's descriptor budget
instead: `syslog_forwarder_limit_nofile` lets imfile keep one descriptor per
accumulated file.

## Verification

```bash
# On a forwarding guest: the drop-in exists and rsyslog is happy.
cat /etc/rsyslog.d/10-forward-cribl.conf
rsyslogd -N1
systemctl is-active rsyslog

# End to end: this host's logs appear in Splunk under the os index
#   index=os host=<this-lxc>
```

## Contributing

Changes go through the repo's standard flow: edit in a worktree, pass
`ansible-lint` and the `tests/template_render` fixture, open a PR. Keep ports and
hostnames sourced from the inventory — never hardcode them here.

## License

Apache-2.0, matching the repository.
