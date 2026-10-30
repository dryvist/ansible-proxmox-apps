# proxmox_backup_server

Install Proxmox Backup Server on a plain Debian guest from the community
`pbs-no-subscription` component. Declare one datastore, reconcile its jobs,
and publish a PVE backup API token for Proxmox VE nodes to use.

The enterprise component is never added, and the one the package ships
enabled as its own conffile is removed: it is the only subscription-gated
part, so on an unsubscribed host it answers 401 and every subsequent
`apt update` — including the next converge — fails outright.

That removal runs after the install, which is what keeps a second converge
clean. A host where something else already installed Proxmox Backup Server
with that repository still enabled needs it removed by hand once before the
role's first run, because the role updates the apt cache before it gets there.

## Installation

The role ships with this repository; no external role dependency. Collections
come from the repository requirements file:

```bash
python3 scripts/install_galaxy_requirements.py
```

## Usage

### Datastore on a pre-mounted path (LXC)

The datastore is a host dataset that the container mounts at the datastore
path. The role does not format anything in this mode.

```yaml
- name: Deploy Proxmox Backup Server
  ansible.builtin.include_role:
    name: proxmox_backup_server
  vars:
    proxmox_backup_server_datastore_name: backup
    proxmox_backup_server_datastore_path: /mnt/datastore/backup
    proxmox_backup_server_publish_openbao: true
```

The `pbs_group` inventory group sets these values for every guest tagged `pbs`.

PBS calendar events do not accept a timezone suffix; they use the server's
timezone. The role sets `Etc/UTC` before declaring maintenance jobs,
so the schedule values below are UTC.

### Datastore on a dedicated disk (VM)

Set the device to the disk's stable path. The role formats it and mounts it.

```yaml
  vars:
    proxmox_backup_server_datastore_name: backup
    proxmox_backup_server_datastore_path: /mnt/datastore/backup
    proxmox_backup_server_datastore_device: /dev/disk/by-id/<stable-id>
```

### Controller environment

When publication is on, the Ansible controller needs `BAO_ADDR` and
`BAO_TOKEN` in its environment. The role reads them with `lookup('env', ...)`
and never prints them.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `proxmox_backup_server_datastore_name` | *(required)* | Datastore name |
| `proxmox_backup_server_datastore_path` | *(required)* | Absolute datastore path |
| `proxmox_backup_server_datastore_device` | `""` | Empty: pre-mounted path. Set: a `/dev/disk/by-*` device to format and mount |
| `proxmox_backup_server_datastore_fstype` | `ext4` | Filesystem for a dedicated datastore disk |
| `proxmox_backup_server_timezone` | `Etc/UTC` | Required PBS calendar timezone |
| `proxmox_backup_server_datastore_create_retries` | `90` | Read-back attempts after `datastore create` |
| `proxmox_backup_server_datastore_create_delay` | `10` | Seconds between read-back attempts |
| `proxmox_backup_server_prune_job_id` | `pve-backups-prune` | Prune job ID |
| `proxmox_backup_server_prune_schedule` | `06:55` | Prune job calendar event |
| `proxmox_backup_server_prune_keep_daily` | `7` | Daily snapshots to keep |
| `proxmox_backup_server_prune_keep_weekly` | `4` | Weekly snapshots to keep |
| `proxmox_backup_server_prune_keep_monthly` | `6` | Monthly snapshots to keep |
| `proxmox_backup_server_gc_schedule` | `sat 08:00` | Datastore garbage-collection calendar event |
| `proxmox_backup_server_verify_job_id` | `pve-backups-verify` | Verify job ID |
| `proxmox_backup_server_verify_schedule` | `sun 08:00` | Verify job calendar event |
| `proxmox_backup_server_verify_ignore_verified` | `true` | Skip snapshots verified recently |
| `proxmox_backup_server_verify_outdated_after` | `30` | Days after which a verified snapshot is verified again |
| `proxmox_backup_server_publish_openbao` | `false` | Create the PVE backup identity and publish it to OpenBao |
| `proxmox_backup_server_openbao_mount` | `secret` | KV v2 mount for the published fields |
| `proxmox_backup_server_openbao_path` | `platform/pbs/pve-nodes` | KV v2 path for the published fields |
| `proxmox_backup_server_backup_user_id` | `pve-backup@pbs` | PBS user for Proxmox VE nodes |
| `proxmox_backup_server_backup_token_name` | `pve` | Token name under that user |
| `proxmox_backup_server_status_directory` | `/var/log/data-protection` | Directory for the status file |
| `proxmox_backup_server_snapshot_max_age_hours` | `26` | Newest snapshot age above which the status outcome is `fail` |
| `proxmox_backup_server_repo_url` | vendor URL | Repository base |
| `proxmox_backup_server_repo_component` | `pbs-no-subscription` | Repository component |
| `proxmox_backup_server_repo_suite` | host release codename | Repository suite |
| `proxmox_backup_server_release_key_url` | vendor URL | Archive signing key |
| `proxmox_backup_server_keyring_path` | `/etc/apt/keyrings/proxmox-release.gpg` | Where the key lands |
| `proxmox_backup_server_user` / `_group` | `backup` | Datastore directory owner |

Both datastore variables are deliberately unset: the path is a site decision,
and defaulting it would put backups on the root filesystem without anyone
choosing that. The role asserts both before touching apt.

The vendor publishes amd64 only; the role asserts the architecture rather than
letting apt report a missing package.

`proxmox-backup-manager datastore create` is not trustworthy on its exit code
— it can report `task failed (status unknown)` for a store its own worker log
records as `TASK OK` — and the datastore list is briefly stale afterwards. The
role therefore reads the list back with a bounded retry and asserts the result,
rather than believing the command.

## Datastore mode

With `proxmox_backup_server_datastore_device` empty, the role verifies the
datastore path. The path must be a mount whose source differs from `/`. The
role asserts that and then sets `backup:backup` ownership on the path.

With the device set, the role checks that it is a block device, refuses one
that carries a partition table or another filesystem, formats it, and mounts
it by UUID. It then asserts the datastore sits on its own filesystem.

## Maintenance jobs

The role reconciles three jobs on the datastore:

- A prune job keeps 7 daily, 4 weekly and 6 monthly snapshots.
- The garbage-collection schedule is set on the datastore.
- A verify job checks snapshots on its own schedule.

Each job is created when absent. It is updated only when a listed value
differs, so a second converge changes nothing.

## PVE backup identity and OpenBao

When `proxmox_backup_server_publish_openbao` is true, outside check mode, the
role does the following:

1. Creates the user `pve-backup@pbs` if it is absent.
2. Creates the token `pve` under that user if it is absent.
3. Grants `DatastoreBackup` on `/datastore/<name>` to the user and to the
   token. PBS intersects token and user permissions, so both need the grant.
4. Writes four fields to the KV v2 path: `PBS_TOKEN_ID`, `PBS_TOKEN_SECRET`,
   `PBS_FINGERPRINT` and `PBS_DATASTORE`. Other fields at that path stay.
5. Reads the four fields back and asserts they match.

The fingerprint comes from `proxmox-backup-manager cert info`. The role
asserts that it is a SHA-256 fingerprint.

### Token and rotation

PBS returns the token secret once, when it creates the token. The role
therefore mints the token only when PBS has none. It writes the secret to
OpenBao in the same run.

If the token exists in PBS but OpenBao has no secret for it, the converge
fails. The role does not mint a new token on its own. To rotate, or to
recover from that failure, delete the token and converge again:

```bash
proxmox-backup-manager user delete-token pve-backup@pbs pve
```

Deleting the token invalidates its secret. Every Proxmox VE node that uses
the token needs the new secret, which its own role reads from OpenBao.

## Status file

The role installs an hourly systemd timer, `pbs-data-protection-status.timer`.
It runs a script that appends lines to
`/var/log/data-protection/pbs.status` (`<mechanism>.status`, per the data-protection standard). Each line has the fields
`ts host mechanism job class outcome age_seconds`. The mechanism is `pbs`, and
the class is `P2`.

Each run writes four lines:

- `snapshot-age`, for the newest snapshot in the datastore.
- `verify-<job>`, for the last verify task.
- `prune-<job>`, for the last prune task.
- `garbage-collection-<datastore>`, for the last garbage-collection task.

The prune row matches its task by job ID or datastore name.

A job with no matching task reports `fail` and `-1`. When no task matches,
a `pbs-status-diag:` line goes to the journal. A datastore with no
snapshots reports `fail` and `-1` for `snapshot-age`; the same outcome is
reported when its newest snapshot is older than
`proxmox_backup_server_snapshot_max_age_hours`. The first line is written at
the next hourly tick.

PBS sends its own notifications by email or Gotify. The `pbs_group` syslog
forwarder ships this status file and the PBS task logs.

## Testing

```bash
molecule test -s proxmox_backup_server
```

Contract tests run without a PBS host:

```bash
python3 -m pytest -q tests/test_proxmox_backup_server_contract.py
```

The status-script test runs the rendered script against a stub
`proxmox-backup-manager`. It needs GNU `date` on `PATH`.

## License

Apache-2.0, as for the rest of this repository.
