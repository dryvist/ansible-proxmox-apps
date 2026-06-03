---
name: inventory-patterns
description: OpenTofu-driven inventory consumption
---

# Inventory Patterns

## Principle

Inventory is loaded dynamically from OpenTofu state via
`inventory/tofu_inventory.json`. The `load_tofu.yml` playbook
must run before all other playbooks. It also delegates `tofu_data`
to all inventory hosts so roles can access it without indirection.

## Data Structure

The tofu_inventory.json contains:

```json
{
  "containers": { ... },
  "vms": { ... },
  "splunk_vm": { ... },
  "docker_vms": { ... },
  "constants": {
    "service_ports": {
      "splunk_web": "...",
      "splunk_hec": "...",
      ...
    },
    "syslog_ports": {
      "unifi": "...",
      "palo_alto": "...",
      ...
    }
  }
}
```

## Accessing Values

### Host Information

Host type determines which keys are available:

```yaml
# VMs and Splunk VM — use ansible_host for the IP
splunk_ip: "{{ hostvars['splunk']['ansible_host'] }}"

# LXC containers — use container_ip for the IP
cribl_ip: "{{ hostvars['cribl-edge-01']['container_ip'] }}"

# Containers — Proxmox guest ID
proxmox_vmid: "{{ hostvars['cribl-edge-01']['proxmox_vmid'] }}"

# Hostname (all host types)
hostname: "{{ hostvars['splunk']['hostname'] }}"
```

### Port Constants

`tofu_data` is delegated to all hosts by `load_tofu.yml`,
so roles access it directly:

```yaml
# Service port
port: "{{ tofu_data.constants.service_ports.splunk_hec }}"

# Syslog ports as a list
ports: "{{ tofu_data.constants.syslog_ports.values() | list }}"

# Syslog ports as key/value pairs
ports: >-
  {{ tofu_data.constants.syslog_ports
     | dict2items(key_name='name', value_name='port') }}
```

## Validation

The `load_tofu.yml` playbook validates that:

1. `tofu_inventory.json` exists
2. The `constants` section is present

If validation fails, regenerate the inventory from terraform-proxmox.

## Regenerating Inventory

```bash
./scripts/sync-tofu-inventory.sh
```
