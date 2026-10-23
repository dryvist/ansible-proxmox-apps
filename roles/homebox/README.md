# homebox

Installs [Homebox](https://github.com/sysadminsmedia/homebox), a home inventory
web app, as a native Go binary on an LXC. The web UI and API share one port.
State lives in the shared native Postgres cluster. Uploaded documents (manuals,
receipts) live on a persistent bind mount, `/var/lib/homebox`, which
tofu-proxmox provisions. The role sets ownership on that mount and never
creates it.

## Installation

Run the role through the `homebox` play in `playbooks/site/04d-homebox.yml`.
The play targets `homebox_group`. Membership comes from the `homebox` guest tag.

```bash
scripts/run-ansible.sh playbooks/site/04d-homebox.yml \
  --tags homebox --limit homebox_group,localhost
```

- The controller downloads the release archive and checks it against the
  release's `checksums.txt`, fetched at the pinned version, before anything is
  extracted. The guest has no route to GitHub.
- The pin is `homebox_version`. Renovate bumps it through the annotation on that
  line.
- The archive is pinned to the newest stable release at least 7 days old. The
  org-wide Renovate preset enforces that minimum age.
- The binary lands at `/opt/homebox/homebox`. It runs as the `homebox` system
  user through `homebox.service`, which has `Restart=on-failure`.
- Configuration is an environment file, `/etc/homebox/homebox.env`, mode 0600,
  rendered with `no_log`. It holds the database password.
- The health check polls `http://127.0.0.1:<homebox_port>/api/v1/status` with
  the same retry shape as the vikunja role.

## Usage

Always include `localhost` in `--limit`, so the inventory loader runs. After a
converge, check the service on the guest:

```bash
systemctl status homebox
curl -fsS "http://127.0.0.1:<homebox_port>/api/v1/status"
```

## Configuration

Every variable follows the upstream loader convention: `HBOX_` plus the Go
config struct path in upper snake case. The names below were re-verified against
the upstream source at the pinned release,
`backend/internal/sys/config/conf.go` and `conf_database.go`.

| Environment variable | Set to | Source |
| --- | --- | --- |
| `HBOX_MODE` | `production` | `Config.Mode` |
| `HBOX_WEB_PORT` | `homebox_port` | `WebConfig.Port` |
| `HBOX_WEB_MAX_UPLOAD_SIZE` | `homebox_web_max_upload_size` (MB) | `WebConfig.MaxUploadSize` |
| `HBOX_STORAGE_CONN_STRING` | `file://<homebox_data_dir>` | `Storage.ConnString` |
| `HBOX_DATABASE_DRIVER` | `postgres` | `Database.Driver` |
| `HBOX_DATABASE_HOST` | `homebox_db_host` | `Database.Host` |
| `HBOX_DATABASE_PORT` | `homebox_db_port` | `Database.Port` |
| `HBOX_DATABASE_USERNAME` | `homebox_db_user` | `Database.Username` |
| `HBOX_DATABASE_PASSWORD` | `homebox_db_password` (OpenBao) | `Database.Password` |
| `HBOX_DATABASE_DATABASE` | `homebox_db_name` | `Database.Database` |
| `HBOX_DATABASE_SSL_MODE` | `disable` | `Database.SslMode` (upstream default `require`) |
| `HBOX_DATABASE_SQLITE_PATH` | molecule only | `Database.SqlitePath` |
| `HBOX_OPTIONS_TRUST_PROXY` | `true` | `Options.TrustProxy` |
| `HBOX_OPTIONS_ALLOW_REGISTRATION` | `homebox_options_allow_registration` | `Options.AllowRegistration` |
| `HBOX_OPTIONS_ALLOW_ANALYTICS` | `false` | `Options.AllowAnalytics` |
| `HBOX_OPTIONS_GITHUB_RELEASE_CHECK` | `false` | `Options.GithubReleaseCheck` |

### Why `ssl_mode` is `disable`

The shared Postgres cluster configures no server TLS. Its `pg_hba` rules use
plain `host` lines with scram-sha-256, so non-TLS connections are accepted and
`require` cannot connect. Vikunja's config carries no TLS setting and connects
to the same listener.

### First account, then close registration

`homebox_options_allow_registration` defaults to `true` so the first account can
be created. Once that account exists, set it to `false` in the inventory and
converge. Registration then closes, and the environment file no longer allows
new sign-ups.

## Backups

`tasks/backup.yml` runs restic from the Debian package and `pg_dump` from the
PGDG client, which matches the shared server's major version. Each run dumps the
Postgres database and copies `/var/lib/homebox`. Each repository has its own
template service instance, so one failing does not skip the other. A weekly
`restic check` runs per repository. The local RustFS repository is always
configured. The offsite Backblaze B2 repository is configured only when its
record supplies an endpoint, a bucket and a key pair. Otherwise the role logs a
debug message and skips it. See the backup section of the role's tasks for the
exact units.

## Secrets the operator supplies

The offsite repository reads its record from OpenBao (`homebox_backup_b2`):
`AWS_ENDPOINT_URL`, `BUCKET`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
No environment variable sets it.

The RustFS endpoint comes from the same OpenBao record that carries the RustFS
keys (`AWS_ENDPOINT_URL`), as the pgBackRest repository does. Nothing needs to
be set by hand for it.

## Testing

`molecule/homebox` converges this role with a sqlite database and backups
disabled. The database server and the backup network paths are the parts it
does not exercise. It verifies the binary install, the unit, and the status
endpoint.
