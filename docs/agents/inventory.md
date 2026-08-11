# Inventory

Inventory is loaded dynamically via `load_tofu.yml`, which resolves its
source in priority order: `TOFU_INVENTORY_PATH` (explicit pin) → the
**RustFS published artifact** (written natively by the tofu-proxmox Terrakube
workspace; fetched with `amazon.aws` using credentials read directly from
OpenBao `secret/platform/object-storage`).
Port constants come from `tofu_data.constants`
(defined in tofu-proxmox `locals.tf`).

This repo is a **read-only consumer** — it never reads `deployment.json`; the
published inventory is the source of truth, fetched fresh with no authoritative
local copy. The upstream desired-state's ACID single-writer contract is
documented once at
[Deployment state contract](https://docs.jacobpevans.com/infrastructure/deployment-state-contract).

## Groups (from tofu inventory)

- `lxc_containers`: All LXC containers (`proxmox_pct_remote` connection)
- `cribl_edge`: Cribl Edge LXC containers (syslog processing)
- `cribl_stream_group`: Cribl Stream LXC containers (netflow/IPFIX processing)
- `docker_vms` / `cribl_docker_group`: Docker Swarm hosts (SSH, testing/dev + CI runners)
- `idrac_kvm_group`: Docker VMs tagged `idrac` (iDRAC KVM viewer VM 251)
- `mailpit_group`: Containers tagged `smtp` (Mailpit SMTP relay)
- `ntfy_group`: Containers tagged `push` (ntfy push notifications)

## Environment Variables

| Variable | Purpose | Source |
| --- | --- | --- |
| `TOFU_INVENTORY_PATH` | Explicit inventory file pin (tests/overrides) | env (optional) |
| `ANSIBLE_CONVERGE_TELEMETRY_ENABLED` | Off switch for converge-freshness telemetry (default on) | env (optional) |
| `TOFU_INVENTORY_S3_URI` | Override the published-inventory S3 location | env (optional) |
| `BAO_ADDR` | Internal OpenBao API used by the inventory resolver | env |
| `BAO_TOKEN` | Secret-zero token allowed to read the object-storage path | env |
| `PROXMOX_VE_NODE` | Proxmox node name | SOPS |
| `PROXMOX_VE_GATEWAY` | Network gateway (for IP derivation) | Doppler / SOPS |
| `PROXMOX_DOMAIN` | Internal DNS domain | Doppler / SOPS |
| `PROXMOX_SSH_KEY_PATH` | SSH key for Proxmox VE host and non-Docker VM access | Doppler / SOPS |
| `PROXMOX_DKR_SSH_KEY_PATH` | SSH key for Docker VM direct access (docker-host) | Doppler / SOPS |
| `SPLUNK_HEC_TOKEN` | Splunk HEC token (for Cribl output) | Doppler / SOPS |
| `SPLUNK_PASSWORD` | Splunk admin password (for E2E validation) | Doppler / SOPS |
| `HAPROXY_STATS_PASSWORD` | HAProxy stats page password | SOPS |
| `TECHNITIUM_DNS_API_TOKEN` | Technitium DNS API token | Doppler |
| `INT_HOMELAB_HARDWARE` | Path to the generated hardware seed slice (Nautobot Devices + Modules) | env (optional) |
| `MAILPIT_RELAY_HOST` | SMTP relay hostname | SOPS |
| `MAILPIT_RELAY_PORT` | SMTP relay port (default 587) | SOPS |
| `MAILPIT_RELAY_USERNAME` | SMTP relay username | SOPS |
| `MAILPIT_RELAY_PASSWORD` | SMTP relay password / app password | Doppler / SOPS |
| `MSSQL_SA_PASSWORD` | SQL Server SA password (for mssql_docker role) | SOPS |
| `GH_PAT_RUNNER_TOKEN` | Fine-grained PAT for runner auto-registration (multi-repo) | Doppler (`gh-workflow-tokens`) |
| `SOPS_AGE_KEY` | Age private key content for SOPS decryption in runner containers | Doppler |
| `GITHUB_RUNNER_TOKEN` | (deprecated) Single-repo registration token (1h expiry) | SOPS |
| `BAO_TOKEN` | Privileged token for reconciling an initialized OpenBao cluster | operator environment |
| `OPENBAO_AWS_ROOT_ACCESS_KEY_ID` | AWS engine bootstrap/rotation access key | tier-0 injection |
| `OPENBAO_AWS_ROOT_SECRET_ACCESS_KEY` | AWS engine bootstrap/rotation secret key | tier-0 injection |
| `OPENBAO_AWS_TF_PROXMOX_ROLE_ARN` | IAM role exposed by `aws/sts/tf-proxmox` | environment |
| `OPENBAO_AWS_IAC_ADMIN_ROLE_ARN` | IAM role exposed by `aws/sts/openbao-iac-admin` | environment |
| `OPENBAO_GITHUB_APP_ID` | Dedicated GitHub broker App ID | one-time environment |
| `OPENBAO_GITHUB_APP_PRIVATE_KEY` | Dedicated GitHub broker App private key | one-time environment |
| `OPENBAO_GITHUB_DRYVIST_INSTALLATION_ID` | GitHub App installation on `dryvist` | environment |
| `OPENBAO_GITHUB_PERSONAL_INSTALLATION_ID` | GitHub App installation on the personal account | environment |
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
