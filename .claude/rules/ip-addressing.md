---
name: ip-addressing
description: No hardcoded values - OpenTofu is authority
---

# IP Addressing Rule

## Principle

**tofu-proxmox is the single source of truth** for all infrastructure
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

**Every service FQDN in this repo has the same shape**:
`<name>.{{ ingress_domain }}`. One variable, declared once
(group_vars/all.yml), used everywhere. The only thing that varies between
two service URLs is the name.

`tofu_data.domain` is the apex. It is NOT an alternative spelling of the
same host: fronted names are published only under `ingress_domain`, so an
apex-built URL resolves to the bare guest or to nothing, bypassing TLS and
the auth gate without raising an error anywhere. Reserve the apex for the
Proxmox nodes themselves.

A port suffix is almost always a mistake too. Fronted services answer on
443 under `ingress_domain`; pinning an app's native port sends the request
to the ingress VIP, which serves nothing there.

```yaml
# GOOD - the one shape, for every fronted service
ntfy_url: "https://ntfy.{{ ingress_domain }}/topic"
grafana_url: "https://grafana.{{ ingress_domain }}"

# GOOD - a shared endpoint variable, defined once in group_vars/all.yml
splunk_hec_url: "{{ splunk_hec_base_url }}/services/collector"

# GOOD - a non-fronted guest keeps its native port, but the SAME zone:
# ingress_domain resolves to the guest itself when no route fronts it
postgres_host: "postgres.{{ ingress_domain }}"

# GOOD - port from tofu constants
splunk_hec_port: "{{ tofu_data.constants.service_ports.splunk_hec }}"

# GOOD - port list from tofu constants
syslog_ports: "{{ tofu_data.constants.syslog_ports.values() | list }}"

# BAD - a fronted name built from the apex: does not resolve
ntfy_url: "https://ntfy.{{ tofu_data.domain }}/topic"

# BAD - a bare fronted name plus a port: the VIP serves nothing there
splunk_hec_url: "https://splunk.{{ ingress_domain }}:{{ hec_port }}"
```

## Updating Values

To change any port or IP:

1. Update `tofu-proxmox/main/locals.tf`
2. Run the tofu-proxmox Terrakube workspace — the apply natively publishes
   the inventory object, which `load_tofu.yml` fetches directly. There is no
   manual regeneration step and no local cache.

## Documentation

Never document specific port numbers or IPs in this repository.
Document HOW to retrieve values, not the values themselves.
