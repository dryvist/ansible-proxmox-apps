# Ansible Proxmox Apps — AI Agent Documentation

Configure applications on Proxmox VMs and LXC containers.
VMs/containers are provisioned by `terraform-proxmox`;
this repo handles app config only.

## This Repo Owns

- **Cribl Edge** (`cribl_edge` role — native install on LXC containers)
- **Cribl Stream** (`cribl_stream` role — native install on LXC containers)
  - Fleet policy: Cribl Cloud fleets are reserved for Linux machines
    (the LXC/VM nodes this repo deploys). macOS hosts run standalone,
    GitOps-managed Edge nodes (see nix-darwin docs/CRIBL-GITOPS.md).
- **HAProxy** (LXC container, syslog/netflow VIP forwarding to Cribl LXCs)
- **Syslog forwarding** (`syslog_forwarder` role — rsyslog on every infra LXC
  ships host + native-service logs to the HAProxy syslog VIP on the Linux port
  -> Cribl Edge -> Splunk `os` index; the pipeline (Cribl) and LB (HAProxy) LXCs
  are excluded to avoid feedback loops)
- **Technitium DNS** (LXC container)
- **apt-cacher-ng** (LXC container)
- **Mailpit** (LXC container, SMTP relay with web UI)
- **ntfy** (LXC container, push notification server)
- **GitHub Actions Runners** (`github_runner` role — Docker Compose on docker-host VM)
- **Qdrant** (`qdrant_docker` role — Docker in LXC container)
- **LlamaIndex** (`llamaindex` role — Python + Ollama CPU-only embeddings on LXC container)
- **iDRAC KVM** (`idrac_kvm_docker` role — domistyle/idrac6 HTML5 KVM viewer +
  host `ipmitool`, Docker on dedicated VM 251). A Mac-only OrbStack exploratory
  variant lives at `orbstack-kubernetes/docker/idrac-webtop` (webtop +
  OpenWebStart + self-signed jar wrapper) and is not used in production.
- **Media stack** (pve2): `download_vpn` (qBittorrent-nox + Prowlarr behind
  Proton WireGuard with a fail-closed dual-stack nftables killswitch, NAT-PMP
  port forwarding, and three layers of continuous killswitch validation), plus
  LAN-only `sonarr`, `radarr`, `plex` (install + idempotent non-fatal claim +
  library-section creation), `seerr` (request UI, Docker-in-LXC), and
  `servarr_wiring` (idempotent API self-wiring: deterministic API keys, public
  Prowlarr indexers, Prowlarr -> Sonarr/Radarr app sync, and media-management
  settings — hardlinks + recycler bin). Root folders + qBittorrent download
  clients are owned by the devopsarr `servarr-config` tofu module
  (`terraform-proxmox`); quality profiles + custom formats by the `configarr`
  role (TRaSH-Guides). `servarr_wiring` no longer touches those.
- **Sortarr** (`sortarr` role — read-only media-library insights dashboard,
  Docker-in-LXC; reaches Sonarr/Radarr/Plex over the LAN via their existing
  API keys, no new *arr-side wiring).
- **Hermes agent** (`hermes_agent` role — the autonomous NousResearch agent
  gateway, native install; not the LLM serving stack).
- **LLM fabric** (`llm_router` role — LiteLLM proxy, the single OpenAI-compatible
  front door for the large/light tiers; `open_webui`, `llama_cpp`, `ollama`
  roles for the backends).

**This repo does NOT own Splunk.** Splunk is managed by `ansible-splunk`.

## Pipeline Data Flow

```text
Sources: external (network gear, OS hosts) + infra LXCs self-logging
         (syslog_forwarder role, Linux port 1517)
         -> HAProxy LXC (175, TCP+UDP 514-518, 1514-1518, 2055)
           |
       Cribl Edge LXCs (180, 181) [syslog ports 1514-1518]
         - Pipeline: sets index + sourcetype by port
         - Output: Splunk HEC (https, port 8088)
           |
       Cribl Stream LXCs (182, 183) [IPFIX port 2055]
         - Pipeline: sets index=network, sourcetype=ipfix
         - Output: Splunk HEC (https, port 8088)
           |
       Splunk Enterprise (200, managed by ansible-splunk)
```

## Production vs Testing Environments

| Environment | Infrastructure | Purpose |
| --- | --- | --- |
| **Production** | LXC containers, Proxmox VMs | Real pipeline workflows, production data |
| **Testing/Dev** | Docker Swarm on docker-host VM | Non-production experiments, Molecule tests |

**Rule:** ALL production log/network pipelines flow through LXC containers.
Docker Swarm on docker-host (250) is the non-production zone for development
and testing only. High-volume network traffic must never flow through
Docker's virtualized networking stack.

### docker-host VM (250) — Workload Classes

| Class | Services | Network | Ansible Tags |
| --- | --- | --- | --- |
| **CI (production)** | GitHub Actions runners | `ci_runners` bridge | `github_runner` |
| **Dev/Test** | Cribl Docker Stack, mssql, etc. | Swarm overlay / default bridge | `cribl_docker_stack`, `mssql_docker` |

These workload classes are isolated by Docker network and Compose project.
CI runners MUST NOT share Docker networks with dev/test services.

### Syslog Port Assignments (from tofu pipeline_constants)

| Port | Source | Splunk Index |
| --- | --- | --- |
| 1514 | UniFi | unifi |
| 1515 | Palo Alto | firewall |
| 1516 | Cisco ASA | firewall |
| 1517 | Linux | os |
| 1518 | Windows | os |

### NetFlow Port (from tofu pipeline_constants)

| Port | Source | Splunk Index |
| --- | --- | --- |
| 2055 | UniFi IPFIX (UDP) | network |

### Service Ports (from tofu pipeline_constants)

| Port | Service |
| --- | --- |
| 8000 | Splunk Web UI |
| 8088 | Splunk HEC (HTTPS) |
| 8089 | Splunk Management |
| 8404 | HAProxy Stats |
| 9420 | Cribl Edge API |
| 9000 | Cribl Stream API (also S3 API on `object-storage` LXC; `minio` LXC during 30-day soak) |
| 9001 | object-storage Console (loopback only; `minio` Console during 30-day soak) |
| 3142 | apt-cacher-ng |
| 1025 | Mailpit SMTP |
| 8025 | Mailpit Web UI |
| 8080 | ntfy HTTP |
| 6333 | Qdrant HTTP (from tofu `vector_db_ports`) |
| 6334 | Qdrant gRPC (from tofu `vector_db_ports`) |

Values are sourced from `terraform-proxmox/locals.tf`
`pipeline_constants.{service_ports, netflow_ports, vector_db_ports}`.
Do not hand-edit — fix the constant and refresh
`inventory/tofu_inventory.json`.

## Inventory

Inventory is loaded dynamically via `load_tofu.yml`, which resolves its
source in priority order: `TOFU_INVENTORY_PATH` (explicit pin) → the
**S3 published artifact** (written natively by every terraform-proxmox
`terragrunt apply`; fetched with `amazon.aws` modules — no checkout, no
toolchain, only AWS read creds) → the local gitignored
`inventory/tofu_inventory.json` cache the apply's after-hook writes.
Port constants come from `tofu_data.constants`
(defined in terraform-proxmox `locals.tf`).

This repo is a **read-only consumer** — it never reads `deployment.json`; the
published inventory is the source of truth, fetched fresh with no authoritative
local copy. The upstream desired-state's ACID single-writer contract is
documented once at
[Deployment state contract](https://docs.jacobpevans.com/infrastructure/deployment-state-contract).

### Groups (from tofu inventory)

- `lxc_containers`: All LXC containers (`proxmox_pct_remote` connection)
- `cribl_edge`: Cribl Edge LXC containers (syslog processing)
- `cribl_stream_group`: Cribl Stream LXC containers (netflow/IPFIX processing)
- `docker_vms` / `cribl_docker_group`: Docker Swarm hosts (SSH, testing/dev + CI runners)
- `idrac_kvm_group`: Docker VMs tagged `idrac` (iDRAC KVM viewer VM 251)
- `mailpit_group`: Containers tagged `smtp` (Mailpit SMTP relay)
- `ntfy_group`: Containers tagged `push` (ntfy push notifications)
- `qdrant_group`: Containers tagged `vectordb` (Qdrant vector database)
- `llamaindex_group`: Containers tagged `rag` (LlamaIndex RAG engine)

### Environment Variables

| Variable | Purpose | Source |
| --- | --- | --- |
| `TOFU_INVENTORY_PATH` | Explicit inventory file pin (tests/overrides) | env (optional) |
| `TOFU_INVENTORY_S3_URI` | Override the published-inventory S3 location | env (optional) |
| `TOFU_INVENTORY_S3_REGION` | Region of the inventory bucket (default `us-east-2`) | env (optional) |
| `PROXMOX_VE_NODE` | Proxmox node name | SOPS |
| `PROXMOX_VE_GATEWAY` | Network gateway (for IP derivation) | Doppler / SOPS |
| `PROXMOX_DOMAIN` | Internal DNS domain | Doppler / SOPS |
| `PROXMOX_SSH_KEY_PATH` | SSH key for Proxmox VE host and non-Docker VM access | Doppler / SOPS |
| `PROXMOX_DKR_SSH_KEY_PATH` | SSH key for Docker VM direct access (docker-host) | Doppler / SOPS |
| `SPLUNK_HEC_TOKEN` | Splunk HEC token (for Cribl output) | Doppler / SOPS |
| `SPLUNK_PASSWORD` | Splunk admin password (for E2E validation) | Doppler / SOPS |
| `HAPROXY_STATS_PASSWORD` | HAProxy stats page password | SOPS |
| `TECHNITIUM_DNS_API_TOKEN` | Technitium DNS API token | Doppler |
| `MAILPIT_RELAY_HOST` | SMTP relay hostname | SOPS |
| `MAILPIT_RELAY_PORT` | SMTP relay port (default 587) | SOPS |
| `MAILPIT_RELAY_USERNAME` | SMTP relay username | SOPS |
| `MAILPIT_RELAY_PASSWORD` | SMTP relay password / app password | Doppler / SOPS |
| `MSSQL_SA_PASSWORD` | SQL Server SA password (for mssql_docker role) | SOPS |
| `GH_PAT_RUNNER_TOKEN` | Fine-grained PAT for runner auto-registration (multi-repo) | Doppler (`gh-workflow-tokens`) |
| `SOPS_AGE_KEY` | Age private key content for SOPS decryption in runner containers | Doppler |
| `GITHUB_RUNNER_TOKEN` | (deprecated) Single-repo registration token (1h expiry) | SOPS |
| `QDRANT_API_KEY` | Qdrant vector database API key | SOPS |
| `IDRAC_R410_HOST` | R410 iDRAC IP/hostname | Doppler |
| `IDRAC_R410_USER` | R410 iDRAC username | Doppler |
| `IDRAC_R410_PASSWORD` | R410 iDRAC password | Doppler |
| `IDRAC_R710_HOST` | R710 iDRAC IP/hostname | Doppler |
| `IDRAC_R710_USER` | R710 iDRAC username | Doppler |
| `IDRAC_R710_PASSWORD` | R710 iDRAC password | Doppler |
| `SONARR_API_KEY` | Deterministic Sonarr API key (servarr_wiring/seerr) | SOPS |
| `RADARR_API_KEY` | Deterministic Radarr API key (servarr_wiring/seerr) | SOPS |
| `PROWLARR_API_KEY` | Deterministic Prowlarr API key (servarr_wiring) | SOPS |
| `SEERR_API_KEY` | Deterministic Seerr API key (seerr role) | SOPS |
| `PLEX_CLAIM_TOKEN` | Optional fresh Plex claim token (~4-min); passed ad-hoc to a converge or done via the web UI, never stored | ad-hoc / web UI |
| `PLEX_TOKEN` | Optional Plex account-token override; normally auto-discovered from the claimed server | env (optional) |

## Secrets Management

**Runtime injection**: Doppler (`doppler run --`)
**At-rest encryption**: SOPS + age (`secrets.enc.yaml`)

See the [SOPS integration rule](agentsmd/rules/infra/sops-integration.md)
in ai-assistant-instructions for full patterns.

Template: `secrets.enc.yaml.example` — copy, fill in real values, then encrypt.

**OpenBao is repointing in.** The `openbao_secrets` role is a `site.yml`
prefetch play (`localhost`, `run_once`) that logs in to OpenBao once per
resource domain (its own least-privilege AppRole) and publishes each domain's
KV subtree as `bao_<domain>_secrets`. Consumer roles read bao-first with an
env fallback:

```yaml
SOME_SECRET: >-
  {{ bao_<domain>_secrets.SOME_SECRET
     | default(lookup('env', 'SOME_SECRET'), true)
     | mandatory('SOME_SECRET must be set (OpenBao secret/<domain>/<path> or SOPS/Doppler env)') }}
```

To repoint a role: seed the domain's KV path in OpenBao, add the path to
`roles/openbao_secrets/defaults/main.yml`, then change the role default to
the pattern above. Leave the old Doppler/SOPS value in place (annotated
superseded) until the converge is proven against the new path — delete it in
a separate follow-up PR, not the same one. `local-llm` is fully repointed;
`media`/`local-cloud`/`monitoring` are seeded but still Doppler-read;
`mssql`/`idrac` have no domain yet.

## Commands

```bash
# Deploy all apps (Doppler — main pipeline does not require SOPS)
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml

# Deploy all apps including SOPS-only roles (e.g., haproxy, mailpit)
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml'

# Deploy GitHub runners (requires token from gh-workflow-tokens Doppler project)
doppler run -p gh-workflow-tokens -c prd -- \
  doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags github_runner

# Edit encrypted secrets
sops secrets.enc.yaml

# Validate pipeline
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/validate-pipeline.yml

# Validate media stack (Prowlarr indexer health + Prowlarr->Radarr/Sonarr sync)
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-media.yml'
# Add --tags deep to actively test each indexer against its tracker (slow, live)

# Re-trigger searches for pending monitored items (Sonarr + Radarr). Standalone,
# on-demand; never part of site.yml. Scope with --tags sonarr (or --tags radarr).
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/search-missing.yml'

# Lint
ansible-lint
```

> **`--limit` must include `localhost`.** The inventory loader
> (`inventory/load_tofu.yml`) runs on `hosts: localhost` and populates the
> dynamic inventory via `add_host`. Running with `--limit <group>` but **not**
> `localhost` silently skips the loader, so no hosts are added and every play
> reports "no hosts matched". Always use `--limit <group>,localhost`.

## Testing

### Fast (CI + pre-commit — runs automatically)

| Check | Command | When |
| --- | --- | --- |
| Ansible lint | `ansible-lint` | pre-commit, every PR |
| Playbook syntax | `ansible-playbook --syntax-check` | every PR (CI) |
| Inventory group validation | see below | every PR (CI) |
| Molecule syntax | `molecule syntax` | every PR (CI, roles/molecule changes) |

**Inventory validation locally:**

```bash
cp tests/inventory_load/tofu_inventory.json inventory/tofu_inventory.json
ansible-playbook tests/inventory_load/verify_inventory.yml \
  -i inventory/hosts.yml -c local
```

### Extended (manual — run before merging role changes)

Full Molecule test deploys the `mssql_docker` role in a Docker container,
starts SQL Server, and verifies port 1433 is accepting connections.
Requires Docker on the local machine (~5-10 min).

```bash
# Install Ansible Galaxy dependencies (once)
ansible-galaxy collection install -r requirements.yml

# Run full test cycle (create -> converge -> idempotence -> verify -> destroy)
molecule test

# Or step through individually for debugging
molecule converge   # deploy role into container
molecule verify     # run assertions
molecule destroy    # clean up
```

**When to run:** Any time you modify a role in `roles/` before opening a PR.

## Dev Environment

This repo uses [Nix flakes](https://wiki.nixos.org/wiki/Flakes) + [direnv](https://direnv.net/) for a reproducible dev environment.

### Activation

```sh
direnv allow    # one-time per worktree — auto-activates on cd
```

The shell is provided by the `ansible-apps` shell in
[nix-devenv](https://github.com/JacobPEvans/nix-devenv) via `.envrc`.
There is no local `flake.nix` — direnv fetches and caches the remote shell automatically.

To activate manually without direnv:

```sh
nix develop "github:JacobPEvans/nix-devenv#ansible-apps"
```

### Tools provided

- ansible, ansible-lint, molecule — configuration management
- sops, age — secrets management
- python3 with paramiko, pyyaml, jinja2, jsondiff — Ansible dependencies
- jq, yq, pre-commit — utilities

## Related Repositories

| Repo | Relationship |
| --- | --- |
| terraform-proxmox | Upstream: provisions VMs/containers |
| ansible-splunk | Peer: owns Splunk Enterprise deployment |
| ansible-proxmox | Peer: owns Proxmox host config (kernel, ZFS, firewall) |
