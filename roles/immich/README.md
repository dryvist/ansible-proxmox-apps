# immich

Deploys [Immich](https://immich.app) — self-hosted photo & video backup for
iPhone/Android/Mac/web (an iCloud Photos alternative) — as **Docker-in-LXC**,
mirroring the `seerr` pattern. Runs the official four-service stack
(`immich-server`, `immich-machine-learning`, `valkey`, `postgres`) via
`community.docker.docker_compose_v2`.

## Installation

This role ships in the `ansible-proxmox-apps` repository and is applied via
`playbooks/site.yml`. No separate installation is required beyond cloning the
repo and installing collection dependencies:

```bash
git clone https://github.com/dryvist/ansible-proxmox-apps.git
cd ansible-proxmox-apps
ansible-galaxy collection install -r requirements.yml
```

## Prerequisites

- An LXC tagged `immich` in terraform-proxmox (nesting enabled for Docker), with
  the photo-library ZFS dataset bind-mounted at `immich_library_dir`
  (`/mnt/photos`) — same model as the media stack's `/data`.
- `IMMICH_DB_PASSWORD` provided via SOPS/Doppler (never committed):

  ```bash
  openssl rand -base64 24   # -> IMMICH_DB_PASSWORD
  ```

## Variables

| Variable | Default | Description |
| --- | --- | --- |
| `immich_version` | `release` | Server/ML image tag — pin to `vX.Y.Z` in production |
| `immich_postgres_image` | pinned vectorchord image | Immich's required Postgres image |
| `immich_redis_image` | `valkey/valkey:9` | Redis-compatible cache |
| `immich_library_dir` | `/mnt/photos` | Host ZFS dataset (bind-mount) for the library |
| `immich_data_dir` | `/opt/immich` | Compose project dir + Postgres data |
| `immich_web_port` | `2283` | Host port published for the web UI/API |
| `immich_db_password` | env `IMMICH_DB_PASSWORD` | Postgres password (required) |
| `immich_manage_services` | `true` | False (molecule) renders config but skips compose up |

## Usage

```bash
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook playbooks/site.yml --tags immich'
```

Then open `http://<lxc-ip>:2283`, create the admin account, and install the
Immich mobile app pointed at that URL for automatic phone photo backup.
