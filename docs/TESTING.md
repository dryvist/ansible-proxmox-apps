# Pipeline Testing Documentation

## Pipeline Architecture

```text
Syslog Sources --> HAProxy LXC --> Cribl Edge LXCs --> Splunk HEC
                  (LB)            (Syslog processing)   (Indexing)

NetFlow Sources -> HAProxy LXC --> Cribl Stream LXCs --> Splunk HEC
                   (LB)            (IPFIX processing)    (Indexing)
```

- **Syslog Sources**: Network devices, hosts, and applications sending syslog
- **NetFlow Sources**: Network devices sending IPFIX/NetFlow data
- **HAProxy**: Load balances syslog traffic to Cribl Edge LXCs and netflow traffic to Cribl Stream LXCs
- **Cribl Edge**: Native install on LXC containers (cribl_edge) for syslog ingestion and processing
- **Cribl Stream**: Native install on LXC containers (cribl_stream_group) for netflow/IPFIX processing
- **Splunk HEC**: Receives processed events via HTTP Event Collector

## IP and Port Convention

Application playbooks and roles never hardcode IPs or ports. They read
them from inventory-managed variables loaded by
`inventory/load_tofu.yml`.

### IP Addresses

IPs are derived from OpenTofu inventory and accessed via `hostvars`:

```yaml
# In playbooks and roles
splunk_host: "{{ hostvars['splunk']['ansible_host'] }}"
```

**Note**: For LXC containers using `proxmox_pct_remote` connection
(including `haproxy`), `ansible_host` contains the Proxmox VE hostname
for the connection plugin, not the container's IP. To get the actual
container IP for service testing, use `tofu_data.containers` from
`tofu_inventory.json`.

### Port Constants

Ports are defined once in `inventory/pipeline_constants.json` and merged
into `tofu_data.constants` by `inventory/load_tofu.yml`:

```yaml
# Service ports
splunk_hec_port: "{{ tofu_data.constants.service_ports.splunk_hec }}"
splunk_web_port: "{{ tofu_data.constants.service_ports.splunk_web }}"

# Syslog ports (all assigned ports as a list)
syslog_ports: "{{ tofu_data.constants.syslog_ports.values() | list }}"

# Syslog ports (by source name)
unifi_port: "{{ tofu_data.constants.syslog_ports.unifi }}"
```

### Source of Truth

Port assignments are defined in `inventory/pipeline_constants.json`
(committed to git). IP derivation logic lives in the `terraform-proxmox`
repository. To change port values, edit `pipeline_constants.json`
directly. To regenerate the OpenTofu inventory:

```bash
./scripts/sync-tofu-inventory.sh
```

## Automated Testing

### validate-pipeline.yml -- E2E Data Flow

Validates the full pipeline by sending a test syslog message and confirming
it arrives in Splunk.

```bash
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-pipeline.yml
```

The playbook runs these validation stages:

1. **HAProxy** -- service running, config valid, syslog and netflow ports listening
2. **Cribl Edge** -- LXC containers running, syslog listeners active
3. **Cribl Stream** -- LXC containers running, IPFIX listener active
4. **Splunk** -- VM running, HEC endpoint healthy, token valid
5. **E2E test** -- sends a tagged syslog event and queries Splunk to confirm arrival

Run individual stages with tags:

```bash
# HAProxy only
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-pipeline.yml --tags haproxy

# Splunk only
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-pipeline.yml --tags splunk

# E2E data flow only
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-pipeline.yml --tags e2e
```

Available tags: `haproxy`, `cribl_edge`, `cribl_stream`, `splunk`,
`e2e`, `data_validation`, `validation`, `summary`.

### Required Environment Variables

The validation playbook requires both **secrets** (typically injected via
Doppler) and **non-secret configuration** (usually set in the CI
environment or your local shell).

#### Secrets (via Doppler)

| Variable | Purpose |
| --- | --- |
| `SPLUNK_PASSWORD` | Splunk admin password for search API queries |
| `SPLUNK_HEC_TOKEN` | HEC token for event submission and validation |

#### Non-secret configuration

The following variables are required by `validate-pipeline.yml` and any
playbook that uses `inventory/hosts.yml` together with
`inventory/load_tofu.yml`:

| Variable | Purpose |
| --- | --- |
| `PROXMOX_VE_HOSTNAME` | Hostname or IP of the Proxmox VE endpoint |
| `PROXMOX_SSH_KEY_PATH` | Path to SSH private key for Proxmox VMs |

In addition, these playbooks expect an OpenTofu-generated inventory file:

- `inventory/tofu_inventory.json` must exist and be up to date before
  running `validate-pipeline.yml` or any playbook that relies on
  `inventory/load_tofu.yml`.

## Manual Quick Tests

For ad-hoc verification, use variable-based commands. Retrieve actual
values from OpenTofu inventory or Doppler before running.

### Resolve IPs and Ports from Inventory

```bash
# IPs come from tofu_inventory.json (gitignored, contains real IPs)
HAPROXY_IP=$(jq -r '.containers.haproxy.ip' \
  inventory/tofu_inventory.json)

CRIBL_EDGE_IP=$(jq -r '.containers | to_entries[] | select(.value.tags // [] | contains(["edge"])) | .value.ip' \
  inventory/tofu_inventory.json | head -1)

CRIBL_STREAM_IP=$(jq -r '.containers | to_entries[] | select(.value.tags // [] | contains(["stream"])) | .value.ip' \
  inventory/tofu_inventory.json | head -1)

SPLUNK_IP=$(jq -r '.splunk_vm.splunk.ip' \
  inventory/tofu_inventory.json)

# Ports come from pipeline_constants.json (committed)
HAPROXY_STATS_PORT=$(jq -r '.service_ports.haproxy_stats' \
  inventory/pipeline_constants.json)

SPLUNK_HEC_PORT=$(jq -r '.service_ports.splunk_hec' \
  inventory/pipeline_constants.json)

CRIBL_EDGE_API_PORT=$(jq -r '.service_ports.cribl_edge_api' \
  inventory/pipeline_constants.json)

CRIBL_STREAM_API_PORT=$(jq -r '.service_ports.cribl_stream_api' \
  inventory/pipeline_constants.json)
```

### HAProxy

```bash
curl -s http://$HAPROXY_IP:$HAPROXY_STATS_PORT/stats
```

### Cribl

```bash
# Check Cribl Edge health API (on LXC container)
curl -s http://$CRIBL_EDGE_IP:$CRIBL_EDGE_API_PORT/api/v1/health

# Check Cribl Stream health API (on LXC container)
curl -s http://$CRIBL_STREAM_IP:$CRIBL_STREAM_API_PORT/api/v1/health
```

### Splunk HEC

```bash
# Test HEC health
# NOTE: The -k flag disables certificate validation. This is convenient for
# local testing but insecure. Use --cacert for production-like environments.
curl -sk https://$SPLUNK_IP:$SPLUNK_HEC_PORT/services/collector/health

# Send test event
curl -sk https://$SPLUNK_IP:$SPLUNK_HEC_PORT/services/collector/event \
  -H "Authorization: Splunk $SPLUNK_HEC_TOKEN" \
  -d '{"event": "manual-test", "sourcetype": "test", "index": "main"}'
```

## Configuring Syslog Sources

Point syslog sources at the HAProxy IP. Each source type uses a dedicated
port defined in `inventory/pipeline_constants.json`.

To view port assignments:

```bash
jq '.syslog_ports' inventory/pipeline_constants.json
```

HAProxy routes each port to the Cribl Edge backend using round-robin with
health checks.

General configuration pattern for any syslog source:

1. Look up the assigned port in `inventory/pipeline_constants.json`
2. Configure the source to send syslog (UDP or TCP) to `$HAPROXY_IP:$ASSIGNED_PORT`
3. Verify events arrive using the `validate-pipeline.yml` playbook

## Troubleshooting

### No Events in Splunk

Run `validate-pipeline.yml` with specific tags to isolate the failing
component. Start from HAProxy and work forward:

```bash
doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-pipeline.yml \
  --tags haproxy,cribl_edge,splunk
```

### HAProxy Backend Down

- Check the HAProxy stats page for backend status
- Verify Cribl Edge LXC containers are running: `pct status <VMID>` on Proxmox host
- Verify Cribl Stream LXC containers are running: `pct status <VMID>` on Proxmox host
- Confirm network connectivity between HAProxy LXC and Cribl LXCs

### Cribl Not Receiving Events

- Verify Cribl Edge syslog listeners are configured and bound
- Check Cribl Edge service status on LXC: `systemctl status cribl`
- Review Cribl Edge logs: `journalctl -u cribl` or `/opt/cribl/log/`
- For netflow issues, check Cribl Stream service status similarly
- Confirm network connectivity between HAProxy LXC and Cribl LXCs

### Splunk Not Receiving Events

- Test HEC health endpoint directly on the Splunk VM
- Verify the HEC token matches the value in Doppler
- Check Splunk service status on the VM
- Review Splunk logs on the VM

## Verification Checklist

- [ ] HAProxy listening on all syslog ports
- [ ] HAProxy stats page accessible
- [ ] Cribl Edge LXC containers running
- [ ] Cribl Stream LXC containers running
- [ ] Splunk VM running and healthy
- [ ] Splunk HEC endpoint responding
- [ ] HEC token valid
- [ ] E2E test event visible in Splunk index
