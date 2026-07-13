---
name: ip-addressing
description: No hardcoded values - OpenTofu is authority
---

# IP Addressing Rule

## Principle

**terraform-proxmox is the single source of truth** for all infrastructure
constants. This repository CONSUMES values, never DEFINES them.

## Prohibited Patterns

Never hardcode IPs or port numbers in role defaults or tasks, and never wire
an app config to an IP-valued variable when a name exists:

```yaml
# BAD - hardcoded IP with fallback
splunk_host: "{{ hostvars['splunk'].ansible_host | default('<any-ip>') }}"

# BAD - IP-valued hostvar in an app config (the address belongs to DNS)
ntfy_host: "{{ hostvars['ntfy']['container_ip'] }}"

# BAD - hardcoded port
splunk_hec_port: <some-port-number>

# BAD - hardcoded port list
syslog_ports:
  - <port>
  - <port>
```

## Required Patterns

Configs reference services **by FQDN, never by address** — see
[docs/IP_AUTHORITY.md](../../docs/IP_AUTHORITY.md) for the full model and the
short list of legitimate IP consumers (the DNS-record tier itself).
`load_tofu.yml` delegates `tofu_data` to all inventory hosts, so
roles can reference it directly:

```yaml
# GOOD - Traefik-fronted service, by name (port 443 implied)
ntfy_url: "https://ntfy.{{ tofu_data.domain }}/topic"

# GOOD - non-fronted guest, by name + tofu constant port
splunk_host: "splunk.{{ tofu_data.domain }}"

# GOOD - port from tofu constants
splunk_hec_port: "{{ tofu_data.constants.service_ports.splunk_hec }}"

# GOOD - port list from tofu constants
syslog_ports: "{{ tofu_data.constants.syslog_ports.values() | list }}"
```

## Updating Values

To change any port or IP:

1. Update `terraform-proxmox/main/locals.tf`
2. Run the tofu-proxmox Terrakube workspace — the apply natively publishes
   the inventory to S3 and its after-hook refreshes the local
   `inventory/tofu_inventory.json` cache. `load_tofu.yml` resolves S3-first,
   so no manual regeneration step exists.

## Documentation

Never document specific port numbers or IPs in this repository.
Document HOW to retrieve values, not the values themselves.
