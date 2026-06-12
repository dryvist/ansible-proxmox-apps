# sonarr

Sonarr TV-series PVR, LAN-only (no VPN). Skeleton role: minimal native install
plus a systemd service. Indexers and the download client are wired up in the
Sonarr UI after deploy — it reaches Prowlarr + qBittorrent on the
`download-vpn` LXC over the LAN.

## Installation

Provisioned by the `sonarr` LXC in `terraform-proxmox` (pve2, single
`bulk/data` bind-mount at `/data`). Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags sonarr
```

## Requirements

- Debian-based LXC.
- The single `bulk/data` dataset bind-mounted at `/data` (TRaSH
  single-filesystem layout): library root `/data/media/tv`, torrents under
  `/data/torrents` — same filesystem, so imports hardlink instead of copy.

## Key variables

Web UI port comes from OpenTofu (`tofu_data.constants.media_ports.sonarr_web`).
See `defaults/main.yml`.

- `sonarr_install_dir` — install location (default `/opt/Sonarr`).
- `sonarr_data_dir` — app data (default `/var/lib/sonarr`).
- `sonarr_web_port` — web UI port (tofu-derived).

## Usage

```yaml
- name: Configure Sonarr
  hosts: sonarr_group
  become: true
  roles:
    - role: sonarr
```
