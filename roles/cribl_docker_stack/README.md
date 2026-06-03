# cribl_docker_stack

> **Testing/Dev Only**: This role deploys Cribl on Docker Swarm and is
> intended for non-production use only. Production pipelines use the
> `cribl_edge` and `cribl_stream` roles, which install Cribl natively on
> LXC containers.

## Purpose

Deploys Cribl Edge and Cribl Stream as Docker containers on a Docker Swarm
host (the `docker-host` VM). This role exists for development experiments,
Molecule tests, and non-production workflows.

For production syslog and netflow processing, use:

- **`cribl_edge` role**: Native Cribl Edge on LXC containers
  (`cribl_edge`) for syslog ingestion and processing
- **`cribl_stream` role**: Native Cribl Stream on LXC containers
  (`cribl_stream_group`) for netflow/IPFIX processing

## Installation

This role is included in the `ansible-proxmox-apps` repository. No
separate installation is required. Ensure Docker and Docker Swarm are
configured on the target VM before running.

## Usage

Run the role against the `cribl_docker_group` inventory group:

```bash
doppler run -- uv run ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml \
  --limit cribl_docker_group
```

## Architecture

```text
Docker Swarm (docker-host VM, testing/dev only)
├── Cribl Edge container(s)
└── Cribl Stream container(s)
```

Production architecture (managed by cribl_edge and cribl_stream roles):

```text
HAProxy LXC → Cribl Edge LXCs (syslog) → Splunk HEC
            → Cribl Stream LXCs (IPFIX) → Splunk HEC
```

## Role Variables

See `defaults/main.yml` for configurable variables. Port assignments come
from `tofu_data.constants` (see `inventory/pipeline_constants.json`).
