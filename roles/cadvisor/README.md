# cadvisor

Deploy [cAdvisor](https://github.com/google/cadvisor) as a Docker container
on every Docker-in-LXC/VM guest, reporting per-container CPU/memory/network/
disk metrics on port `8080` for the central Prometheus scrape.

## What It Does

1. Creates the compose project directory.
2. Renders and deploys a single-container `docker-compose.yml` (cAdvisor
   image, read-only host mounts for `/`, `/var/run`, `/sys`,
   `/var/lib/docker`, `/dev/disk`, plus the `/dev/kmsg` device it needs for
   the OOM-event log source).
3. Verifies the `/metrics` endpoint answers.

## Installation

No collection dependency beyond `community.docker` (already a repo
requirement for every `*_docker` role). Consumed as an ordinary role
dependency from `playbooks/site.yml`; nothing to install separately.

## Where It Runs

Wired into `playbooks/site.yml` against `docker_vms` only — it has nothing to
report on a guest with no Docker containers to inspect. The `docker_engine`
meta dependency (`meta/main.yml`) installs Docker itself first.

## Usage

```bash
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --limit docker_vms,localhost --tags cadvisor
```

### Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `cadvisor_image` | `gcr.io/cadvisor/cadvisor:v0.49.1` | Pinned upstream image. |
| `cadvisor_container_name` | `cadvisor` | Container name. |
| `cadvisor_port` | `8080` | Host port the metrics endpoint is published on. |
| `cadvisor_data_dir` | `/opt/cadvisor` | Compose project directory. |

## Verification

```bash
curl -s http://<guest-mgmt-ip>:8080/metrics | head
```

## License

Apache-2.0, matching the repository (cAdvisor itself is Apache-2.0).
