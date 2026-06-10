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

Ports are defined once in terraform-proxmox `locals.tf`
(`pipeline_constants`), exported through the `ansible_inventory` output
into `inventory/tofu_inventory.json`, and loaded as `tofu_data.constants`
by `inventory/load_tofu.yml`:

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

Port assignments and IP derivation both live in the `terraform-proxmox`
repository (`locals.tf` `pipeline_constants`). To change port values,
edit them there and apply; the inventory sync hook rewrites
`inventory/tofu_inventory.json` here. To regenerate the OpenTofu
inventory manually:

```bash
./scripts/sync-tofu-inventory.sh
```

## Automated Testing

### Pytest E2E Suites -- Component Isolation

The pytest E2E suites validate the live pipeline one component at a time,
then validate full data flow for every configured syslog source family.
They are also run by `.github/workflows/_e2e-tests.yml` on self-hosted
Linux runners.

| Suite | Command | Validates |
| --- | --- | --- |
| Smoke | `python3 -m pytest tests/e2e/test_smoke.py -v` | Ports and basic service reachability |
| Splunk | `sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_splunk.py -v'` | Splunk export search, HEC health, direct HEC ingest |
| HAProxy | `python3 -m pytest tests/e2e/test_haproxy.py -v` | TCP/UDP standard and high syslog frontends |
| Cribl Edge | `sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_cribl_edge.py -v'` | Edge API/listeners and direct Edge-to-Splunk syslog |
| Syslog Pipeline | `sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_pipeline.py -v'` | Each syslog source through HAProxy to Splunk |
| NetFlow | `sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_forwarding.py -v'` | NetFlow through HAProxy/Cribl Stream to Splunk |
| macOS | `sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_macos.py -v'` | macbook-m4 Cribl Edge freshness |

The syslog source matrix is:

| Source family | App-facing port | Backend port | Splunk index | Sourcetype |
| --- | ---: | ---: | --- | --- |
| UniFi | 514 | 1514 | `unifi` | `ubiquiti:unifi` |
| Palo Alto | 515 | 1515 | `firewall` | `pan:firewall` |
| Cisco ASA | 516 | 1516 | `firewall` | `cisco:asa` |
| Linux | 517 | 1517 | `os` | `syslog` |
| Windows | 518 | 1518 | `os` | `syslog` |

The full syslog pipeline suite sends unique sentinels over TCP and UDP to
the app-facing HAProxy ports, then polls Splunk through
`/services/search/jobs/export` until the event lands with the expected
index and sourcetype.

The scheduled workflow runs every 15 minutes when the repository variable
`E2E_RUNNERS_ENABLED` is set to `true`.

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

Optional pytest overrides:

| Variable | Purpose |
| --- | --- |
| `SPLUNK_MGMT_URL` | Override the Splunk management URL used for export searches |
| `SPLUNK_HEC_URL` | Override the Splunk HEC base URL |
| `PIPELINE_POLL_TIMEOUT_SECONDS` | Override sentinel search timeout, default `120` |
| `PIPELINE_POLL_INTERVAL_SECONDS` | Override sentinel search interval, default `10` |

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

# Ports come from the constants section of tofu_inventory.json
HAPROXY_STATS_PORT=$(jq -r '.constants.service_ports.haproxy_stats' \
  inventory/tofu_inventory.json)

SPLUNK_HEC_PORT=$(jq -r '.constants.service_ports.splunk_hec' \
  inventory/tofu_inventory.json)

CRIBL_EDGE_API_PORT=$(jq -r '.constants.service_ports.cribl_edge_api' \
  inventory/tofu_inventory.json)

CRIBL_STREAM_API_PORT=$(jq -r '.constants.service_ports.cribl_stream_api' \
  inventory/tofu_inventory.json)
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
port defined in the `constants` section of `inventory/tofu_inventory.json`.

To view port assignments:

```bash
jq '.constants.syslog_ports' inventory/tofu_inventory.json
```

HAProxy routes each port to the Cribl Edge backend using round-robin with
health checks.

General configuration pattern for any syslog source:

1. Look up the assigned port in `inventory/tofu_inventory.json` (`.constants.syslog_ports`)
2. Configure the source to send syslog (UDP or TCP) to `$HAPROXY_IP:$ASSIGNED_PORT`
3. Verify events arrive using `tests/e2e/test_pipeline.py`

## Troubleshooting

### No Events in Splunk

Run the component pytest suites to isolate the failing component. Start
from Splunk and HAProxy reachability, then work through Cribl Edge and
full data flow:

```bash
python3 -m pytest tests/e2e/test_haproxy.py -v
sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_splunk.py -v'
sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_cribl_edge.py -v'
sops exec-env secrets.enc.yaml 'python3 -m pytest tests/e2e/test_pipeline.py -v'
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

- [ ] HAProxy listening on all standard syslog ports 514-518
- [ ] HAProxy listening on all high syslog ports 1514-1518
- [ ] HAProxy stats page accessible
- [ ] Cribl Edge LXC containers running
- [ ] Cribl Stream LXC containers running
- [ ] Splunk VM running and healthy
- [ ] Splunk HEC endpoint responding
- [ ] HEC token valid
- [ ] Each syslog source family lands in the expected Splunk index
- [ ] Each syslog source family lands with the expected sourcetype
