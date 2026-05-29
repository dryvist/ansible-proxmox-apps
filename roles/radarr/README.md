# radarr

Radarr movie PVR, LAN-only (no VPN). Skeleton role: minimal native install
plus a systemd service. Indexers and the download client are wired up in the
Radarr UI after deploy — it reaches Prowlarr + qBittorrent on the
`download-vpn` LXC over the LAN.

## Installation

Provisioned by the `radarr` LXC in `terraform-proxmox` (pve2, `tank/media` +
`tank/downloads` bind-mounts). Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags radarr
```

## Requirements

- Debian-based LXC.
- `tank/media` + `tank/downloads` bind-mounted at `/mnt/media` and
  `/mnt/downloads`.

## Key variables

Web UI port comes from terraform (`terraform_data.constants.media_ports.radarr_web`).
See `defaults/main.yml`.

- `radarr_install_dir` — install location (default `/opt/Radarr`).
- `radarr_data_dir` — app data (default `/var/lib/radarr`).
- `radarr_web_port` — web UI port (terraform-derived).

## Usage

```yaml
- name: Configure Radarr
  hosts: radarr_group
  become: true
  roles:
    - role: radarr
```
