# plex

Plex Media Server, LAN-only (no VPN). Skeleton role: installs from Plex's
official apt repo and enables the bundled systemd service. Library setup and
server claim happen in the Plex web UI after deploy.

## Installation

Provisioned by the `plex` LXC in `terraform-proxmox` (pve2, `tank/media`
bind-mount). Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags plex
```

## Requirements

- Debian-based LXC.
- `tank/media` bind-mounted at `/mnt/media`.

## Key variables

Server port comes from terraform (`terraform_data.constants.media_ports.plex_web`).
See `defaults/main.yml`.

- `plex_media_dir` — media library root (default `/mnt/media`).
- `plex_apt_repo` — Plex apt repository line.
- `plex_web_port` — server/web UI port (terraform-derived).

## Usage

```yaml
- name: Configure Plex Media Server
  hosts: plex_group
  become: true
  roles:
    - role: plex
```
