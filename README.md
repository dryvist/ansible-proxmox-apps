# Ansible Proxmox Apps

Configure applications running on Proxmox VMs and containers.

This repository manages application deployment and configuration on virtual
machines and containers provisioned by Proxmox VE. For Proxmox infrastructure
provisioning, see `terraform-proxmox`.

## Purpose and Scope

Deploy and configure the following application stacks:

- **Cribl Edge**: Syslog ingestion and log processing with persistent queue
- **Cribl Stream**: Central processing node for log pipeline
- **HAProxy**: Syslog load balancer distributing logs to Cribl Edge nodes

Cribl Edge, Cribl Stream, and HAProxy run natively on Proxmox LXC
containers. Splunk runs on a Proxmox VM. All infrastructure is provisioned
by `terraform-proxmox`. This repository handles application configuration
only.

## Dependencies

- **terraform-proxmox**: Provisions VMs and persistent storage
- **Doppler**: Secrets management (API keys, passwords)
- Ansible 2.12+
- Python 3.12+

## Installation

```bash
# Clone repository
cd ~/git
git clone <repo-url> ansible-proxmox-apps
cd ansible-proxmox-apps

# Activate Nix dev shell (provides ansible, ansible-lint, molecule, etc.)
direnv allow    # one-time per worktree — auto-activates on cd

# Install required collections
ansible-galaxy collection install -r requirements.yml

# Configure Doppler
doppler configure set project ansible-proxmox-apps
doppler configure set config prd
```

Set the required environment variable for the Proxmox LXC SSH connection:

```bash
export PROXMOX_SSH_KEY_PATH="<path-to-ssh-key>"
```

Each container's Proxmox node host is derived automatically from the inventory
(`{node-role}.{domain}`) — there is no global Proxmox host to set.

## Usage

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

## Inventory

Inventory is loaded dynamically via `inventory/load_tofu.yml`. IPs are
derived from OpenTofu state and accessed via `hostvars`. Port constants
come from `tofu_data.constants` (defined in `terraform-proxmox`).

`load_tofu.yml` resolves the inventory at run time, in priority order
(first that resolves wins):

1. `TOFU_INVENTORY_PATH` — an explicit local file (pin / override, e.g. tests).
2. **S3 published artifact** — `terragrunt apply` publishes the raw
   `ansible_inventory` output to the terraform-proxmox state bucket. Any runner
   with scoped AWS read creds fetches it natively
   (`amazon.aws.aws_caller_info` + `amazon.aws.s3_object`; boto3 comes from
   the dev shell) — **no checkout, no terraform toolchain, no `aws` CLI**.
   Override the location with `TOFU_INVENTORY_S3_URI` (else it is derived
   from the account); region via `TOFU_INVENTORY_S3_REGION` (default
   `us-east-2`).
3. `inventory/tofu_inventory.json` — the local gitignored cache the
   terraform-proxmox after-hook writes on every apply.

## Port Assignments

All port assignments are defined in `inventory/pipeline_constants.json`
and merged into `tofu_data.constants`. See that file for current
values. Do not hardcode ports in playbooks or roles.

## Roles

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

Deploy Cribl Stream and Cribl Edge as Docker containers on the docker-host
VM. This role is for testing and development only. Production pipelines use
the `cribl_edge` and `cribl_stream` roles on native LXC containers.

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
HAProxy) or VMs (Splunk), provisioned by `terraform-proxmox`.

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
│   ├── hosts.yml                Dynamic inventory from env vars
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

## Requirements

See `requirements.yml` for Ansible Galaxy collection dependencies.

Run the following to install:

```bash
ansible-galaxy collection install -r requirements.yml
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

## Development Environment

This project uses [Nix flakes](https://wiki.nixos.org/wiki/Flakes) + [direnv](https://direnv.net/) for a reproducible dev environment.

### Prerequisites

- [Nix](https://nixos.org/download/) with flakes enabled
- [direnv](https://direnv.net/docs/installation.html) with [nix-direnv](https://github.com/nix-community/nix-direnv)

### Setup

```sh
cd ansible-proxmox-apps/main    # or any worktree
direnv allow                    # one-time per worktree
```

### Tools provided

- `ansible`, `ansible-lint`, `molecule` — configuration management
- `sops`, `age` — secrets management
- `python3` with paramiko, pyyaml, jinja2 — Ansible dependencies
- `jq`, `yq`, `pre-commit` — utilities

## Contributing

1. Update inventories in `inventory/`
2. Modify roles in `roles/*/`
3. Test with `--check --diff` mode
4. Validate with `ansible-lint`
5. Run playbook to apply

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.
