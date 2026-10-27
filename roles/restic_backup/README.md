# restic_backup

Nightly [restic](https://restic.net/) backup of one service: an optional PostgreSQL dump plus
optional filesystem paths, to one encrypted repository per entry of `restic_backup_repositories`.
restic comes from the Debian archive and systemd drives everything; there is no custom script.

## Installation

The role installs `restic` from the Debian archive. When `restic_backup_db_name` is set, it also
installs `postgresql-client` from the PGDG repository that the `postgres` role configures, so
`pg_dump` matches the server's major version. With no repository enabled, the role installs
nothing.

## Usage

```yaml
- ansible.builtin.include_role:
    name: restic_backup
  vars:
    restic_backup_name: nautobot
    restic_backup_password: "{{ nautobot_restic_password }}"
    restic_backup_db_name: nautobot
    restic_backup_repositories: "{{ nautobot_backup_repositories }}"
```

`roles/nautobot/tasks/backup.yml` is the consumer.

For a service named `svc` and a repository named `b2`, the role installs these units:

| Unit | Schedule | Runs |
| --- | --- | --- |
| `svc-backup@b2.timer` | daily at 06:10 UTC, `RandomizedDelaySec=600`, `Persistent=true` | `svc-backup@b2.service` |
| `svc-check@b2.timer` | Monday at 06:35 UTC, `RandomizedDelaySec=300`, `Persistent=true` | `svc-check@b2.service` (`restic check`) |

`svc-backup@b2.service` creates the repository when `restic cat config` cannot read it. It streams
`pg_dump -Fc <db>` into `restic backup --stdin` (file name `<name>.dump`), backs up
`restic_backup_paths`, then runs `restic forget --prune` with the keep policy below. Each
repository has its own instance, so one failing does not skip another.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `restic_backup_name` | `""` (required) | Prefix of the units and of `/etc/<name>-backup`. |
| `restic_backup_password` | `""` | Repository password. Required once a repository is enabled. Never change it after the first backup. |
| `restic_backup_db_name` | `""` | Database to dump. Empty skips the dump and the PostgreSQL client. |
| `restic_backup_db_host`, `_port`, `_user`, `_password` | none | Connection for `pg_dump`, through a root-only `pgpass` file. |
| `restic_backup_paths` | `[]` | Extra paths to back up. |
| `restic_backup_repositories` | `[]` | `name`, `enabled`, `bucket`, `endpoint`, `access_key_id`, `secret_access_key`, `region`. |
| `restic_backup_backup_on_calendar` / `_check_on_calendar` | daily 06:10 UTC / Monday 06:35 UTC | Timer `OnCalendar` values. |
| `restic_backup_randomized_delay_sec` / `restic_backup_check_randomized_delay_sec` | `600` / `300` | Backup and check timer splay in seconds. |
| `restic_backup_keep_daily` / `_weekly` / `_monthly` | `14` / `8` / `24` | Retention. |

A repository that is not `enabled` gets no environment file or timers. If an earlier run installed
its timers, the role stops and disables them.

## Testing

`tests/test_restic_backup_render.py` renders each template and checks the unit, timer, environment
file and `pgpass` shapes.

## Contributing

Open a pull request against `develop`. Keep the units free of custom scripts.

## License

Apache-2.0, as the rest of the repository.
