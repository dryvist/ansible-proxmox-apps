# Ansible Proxmox Apps

Configure applications running on Proxmox VMs and LXC containers.

This repository manages application deployment and configuration only. It assumes
the target VMs and containers — and their persistent storage — already exist and
are reachable over SSH. It does not provision infrastructure; it consumes a
published inventory describing the hosts it should configure (see
[Inventory contract](#inventory-contract)).

## Purpose and Scope

Deploy and configure the following application stacks:

- **Cribl Edge**: Syslog ingestion and log processing with persistent queue
- **Cribl Stream**: Central processing node for log pipeline
- **HAProxy**: Syslog/netflow load balancer distributing traffic to Cribl nodes

Cribl Edge, Cribl Stream, and HAProxy run natively on LXC containers. Splunk runs
on a VM. This repository handles application configuration on those hosts; it does
not create them.

## Inventory contract

This repository is configuration-only. It expects the hosts, their IPs, and the
pipeline's port constants to be supplied at run time as a published inventory
artifact — a single JSON document — rather than hardcoded here. Any system that
emits a document matching the shape below can drive these playbooks.

The inventory loader (`inventory/load_tofu.yml`) resolves the artifact at run
time, in priority order (first that resolves wins):

1. `TOFU_INVENTORY_PATH` — an explicit local file (pin / override, e.g. tests).
2. **Published S3 artifact** — the raw inventory JSON fetched natively from S3
   (`amazon.aws.aws_caller_info` + `amazon.aws.s3_object`; boto3 comes from the
   dev shell — no checkout, no provisioning toolchain, no `aws` CLI). Point at it
   with `TOFU_INVENTORY_S3_URI` (else the URI is derived from the active AWS
   account); set the region with `TOFU_INVENTORY_S3_REGION` (default `us-east-2`).
3. `inventory/tofu_inventory.json` — a local gitignored cache.

The resolved document is loaded as `tofu_data` and validated before any play
runs. It MUST contain at least:

- `tofu_data.domain` — the DNS domain used to derive each container's Proxmox
  node host as `{node-role}.{domain}` (so there is no global Proxmox host to set).
- `tofu_data.nodes` — node-name to role mapping, used in the FQDN derivation above.
- `tofu_data.containers`, `tofu_data.vms`, `tofu_data.docker_vms`,
  `tofu_data.splunk_vm` — the hosts to configure, each carrying its IP and
  connection settings; surfaced to roles via `hostvars`.
- `tofu_data.constants` — the pipeline's port assignments. `service_ports` and
  `syslog_ports` are required; roles also read `syslog_port_map`, `netflow_ports`,
  `notification_ports`, and `media_ports`. Ports are never hardcoded in playbooks
  or roles — they are always read from `tofu_data.constants`.

If `tofu_data` is missing required keys, the loader fails loudly before
configuring anything.

## Installation

This repository owns its toolchain via a Nix flake + direnv (`ansible`,
`ansible-lint`, `molecule`, `sops`, `age`, `python3` with paramiko/pyyaml/jinja2,
`jq`, `yq`, `pre-commit`). Run everything inside that dev shell.

```bash
git clone <repo-url> ansible-proxmox-apps
cd ansible-proxmox-apps
direnv allow    # one-time per worktree — auto-activates the dev shell on cd

# Install required Ansible Galaxy collections
ansible-galaxy collection install -r requirements.yml

# Configure Doppler for secrets (API keys, passwords)
doppler configure set project ansible-proxmox-apps
doppler configure set config prd
```

Set the SSH key used to reach the LXC containers. The Docker-VM roles
(testing/dev only) reach their hosts over a separate key, which the inventory
loader requires whenever the inventory contains Docker VMs:

```bash
# SSH key for the LXC containers (production stacks)
export PROXMOX_SSH_KEY_PATH="<path-to-ssh-key>"

# SSH key for the Docker VMs — required when the inventory has docker_vms
export PROXMOX_DKR_SSH_KEY_PATH="<path-to-docker-vm-ssh-key>"
```

## Usage

Run playbooks inside the dev shell, with secrets injected by Doppler. Hosts and
ports come from the published inventory (see
[Inventory contract](#inventory-contract)).

```bash
# Deploy Cribl Edge (syslog processing on LXC containers)
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml --tags cribl_edge

# Deploy Cribl Stream (netflow/IPFIX processing on LXC containers)
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml --tags cribl_stream

# Deploy HAProxy (load balancer on LXC container)
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml --tags haproxy

# Deploy all applications
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml
```

## Roles

### docker_engine (shared dependency)

Shared Docker-in-LXC bootstrap consumed as a meta dependency by the `*_docker`
app roles. Installs Docker CE + the compose plugin and (LXC-conditional) the
fuse-overlayfs storage driver. App roles pull it in via `meta/main.yml`
`dependencies:` instead of repeating the bootstrap block; the apt install work
is skipped on hosts that already have Docker.

The Python venv (`pip install docker`) is **off by default**:
`community.docker.docker_compose_v2` shells out to the `docker compose` CLI and
does not need the docker SDK. Only roles that use the SDK-based modules
(`docker_container`/`_exec`/`_info`, `docker_image`, `docker_swarm`/`_stack`,
`docker_prune`) set `docker_engine_manage_venv: true`. Behaviour is parameterised
through `docker_engine_manage_venv`, `docker_engine_set_global_interpreter`,
`docker_engine_install_fuse_overlayfs`, `docker_engine_configure_daemon_json`,
and `docker_engine_storage_driver`.

### cribl_edge

Deploy Cribl Edge log processor with syslog listeners and Splunk HEC output.

- Installs Cribl Edge from official package repository
- Configures UDP/TCP syslog listeners (ports 1514-1518)
- Configures Splunk HEC output
- Mounts 100GB persistent queue disk at `/opt/cribl/data`

See `roles/cribl_edge/README.md` for detailed configuration.

### cribl_stream

Deploy Cribl Stream as central processing node in the pipeline.

- Installs Cribl Stream from official packages
- Configures as processing node (not leader)
- Mounts 100GB persistent queue disk at `/opt/cribl/data`

See `roles/cribl_stream/README.md` for configuration options.

### haproxy

Production load balancer on a dedicated LXC container.

- Installs HAProxy and Nginx Stream on the HAProxy LXC container
- Forwards syslog traffic (TCP/UDP) to Cribl Edge LXC containers
- Forwards netflow/IPFIX traffic (TCP/UDP) to Cribl Stream LXC containers
- HAProxy stats dashboard available (port from `tofu_data.constants`)

See `roles/haproxy/README.md` for details.

### apt_cacher_ng

APT package caching proxy to reduce bandwidth usage across containers and VMs.

See `roles/apt_cacher_ng/README.md` for configuration.

### cribl_docker_stack (testing/dev only)

Deploy Cribl Stream and Cribl Edge as Docker containers on the docker-host VM.
This role is for testing and development only. Production pipelines use the
`cribl_edge` and `cribl_stream` roles on native LXC containers.

### mailpit_docker

Deploy Mailpit email testing container for local SMTP capture and inspection.

### mssql_docker

Deploy Microsoft SQL Server as a Docker container.

### ntfy_docker

Deploy ntfy push notification service as a Docker container.

### technitium_dns

Deploy Technitium DNS server container for local DNS resolution and blocking.

## Architecture

All production components run on LXC containers (Cribl Edge, Cribl Stream,
HAProxy) or VMs (Splunk).

```text
┌──────────────────┐    ┌──────────────────┐
│  Syslog Sources  │    │ NetFlow Sources   │
└────────┬─────────┘    └────────┬─────────┘
         │                       │
    (UDP/TCP syslog)        (UDP IPFIX)
         │                       │
         ▼                       ▼
┌────────────────────────────────────────┐
│         HAProxy LXC                    │
│         (Load Balancer)                │
└───────┬────────────────────┬───────────┘
        │                    │
   (syslog)             (netflow)
        │                    │
        ▼                    ▼
   ┌─────────┐         ┌──────────┐
   │Cribl    │         │Cribl     │
   │Edge LXCs│         │Stream    │
   │(syslog) │         │LXCs     │
   └────┬────┘         │(IPFIX)  │
        │              └────┬─────┘
        │                   │
        └─────────┬─────────┘
                  │
            (Splunk HEC)
                  │
                  ▼
           ┌──────────────┐
           │    Splunk    │
           │      VM      │
           └──────────────┘
```

## File Layout

```text
ansible-proxmox-apps/
├── README.md                    This file
├── CLAUDE.md                    AI agent documentation
├── ansible.cfg                  Ansible configuration
├── requirements.yml             Ansible Galaxy dependencies
├── .ansible-lint                Linting rules
├── .gitignore                   Git ignore rules
├── .pre-commit-config.yaml      Pre-commit hooks
├── inventory/
│   ├── hosts.yml                Static shared vars (hosts added dynamically)
│   ├── load_tofu.yml            Resolves & validates the inventory artifact
│   └── group_vars/
│       └── all.yml              Global variables
├── playbooks/
│   └── site.yml                 Main playbook (all roles)
└── roles/
    ├── cribl_edge/
    │   ├── README.md
    │   ├── defaults/main.yml
    │   ├── tasks/main.yml
    │   ├── handlers/main.yml
    │   └── templates/
    ├── cribl_stream/
    │   ├── README.md
    │   ├── defaults/main.yml
    │   ├── tasks/main.yml
    │   ├── handlers/main.yml
    │   └── templates/
    └── haproxy/
        ├── README.md
        ├── defaults/main.yml
        ├── tasks/main.yml
        ├── handlers/main.yml
        └── templates/
            └── haproxy.cfg.j2
```

## Linting

Validate code quality with ansible-lint:

```bash
ansible-lint
```

Fix common issues automatically:

```bash
ansible-lint --fix
```

## Contributing

1. Update inventory handling in `inventory/`
2. Modify roles in `roles/*/`
3. Test with `--check --diff` mode
4. Validate with `ansible-lint`
5. Run playbook to apply

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

---

> Part of a [larger ecosystem of ~40 repos](https://docs.jacobpevans.com) — see how it all fits together.
