# proxmox_backup_server

Install Proxmox Backup Server on a plain Debian guest from the community
`pbs-no-subscription` component and declare one datastore.

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
ansible-galaxy install -r requirements.yml
```

## Usage

```yaml
- name: Deploy Proxmox Backup Server
  ansible.builtin.include_role:
    name: proxmox_backup_server
  vars:
    proxmox_backup_server_datastore_name: primary
    proxmox_backup_server_datastore_path: /srv/backup/primary
```

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `proxmox_backup_server_datastore_name` | *(required)* | Datastore name |
| `proxmox_backup_server_datastore_path` | *(required)* | Absolute datastore path |
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

## Testing

```bash
molecule test -s proxmox_backup_server
```

## License

Apache-2.0, as for the rest of this repository.
