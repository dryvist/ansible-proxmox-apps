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
rule uses `omfwd` with a disk-assisted action queue, so a HAProxy/Cribl outage
buffers (up to `syslog_forwarder_queue_max_disk_space`) instead of dropping
logs.

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
| `syslog_forwarder_queue_max_disk_space` | `256m` | Disk-queue cap so a receiver outage buffers instead of dropping. |

Port and target are sourced from the inventory / `PROXMOX_SUBDOMAIN`, never
hardcoded (see `.claude/rules/ip-addressing.md`).

## Verification

```bash
# On a forwarding LXC: the drop-in exists and rsyslog is happy.
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
