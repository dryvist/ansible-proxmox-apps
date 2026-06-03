---
name: ip-addressing
description: No hardcoded values - OpenTofu is authority
---

# IP Addressing Rule

## Principle

**terraform-proxmox is the single source of truth** for all infrastructure
constants. This repository CONSUMES values, never DEFINES them.

## Prohibited Patterns

Never hardcode IPs or port numbers in role defaults or tasks:

```yaml
# BAD - hardcoded IP with fallback
splunk_host: "{{ hostvars['splunk'].ansible_host | default('<any-ip>') }}"

# BAD - hardcoded port
splunk_hec_port: <some-port-number>

# BAD - hardcoded port list
syslog_ports:
  - <port>
  - <port>
```

## Required Patterns

`load_tofu.yml` delegates `tofu_data` to all inventory hosts, so
roles can reference it directly:

```yaml
# GOOD - IP from inventory (no fallback)
splunk_ip: "{{ hostvars['splunk']['ansible_host'] }}"

# GOOD - port from tofu constants
splunk_hec_port: "{{ tofu_data.constants.service_ports.splunk_hec }}"

# GOOD - port list from tofu constants
syslog_ports: "{{ tofu_data.constants.syslog_ports.values() | list }}"
```

## Updating Values

To change any port or IP:

1. Update `terraform-proxmox/main/locals.tf`
2. Run `terragrunt apply` in terraform-proxmox
3. Regenerate inventory:

   ```bash
   ./scripts/sync-tofu-inventory.sh
   ```

## Documentation

Never document specific port numbers or IPs in this repository.
Document HOW to retrieve values, not the values themselves.
