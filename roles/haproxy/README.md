# haproxy

Production load balancer for the Cribl pipeline. HAProxy and Nginx Stream
run on a dedicated LXC container, forwarding syslog traffic to Cribl Edge
LXCs and netflow/IPFIX traffic to Cribl Stream LXCs.

## Purpose

Installs and configures two complementary load balancers on the HAProxy
LXC container:

- **HAProxy**: Load balances TCP syslog traffic to Cribl Edge LXC
  containers, and TCP netflow to Cribl Stream LXC containers
- **Nginx Stream Module**: Load balances UDP traffic (syslog, NetFlow) to
  the appropriate Cribl LXC containers

## Architecture

```text
UDP syslog   → Nginx stream → Cribl Edge LXCs (syslog processing)
TCP syslog   → HAProxy      → Cribl Edge LXCs (syslog processing)
UDP NetFlow  → Nginx stream → Cribl Stream LXCs (IPFIX processing)
TCP NetFlow  → HAProxy      → Cribl Stream LXCs (IPFIX processing)
```

Both services run on the same HAProxy LXC container. The container IP is
derived from OpenTofu inventory (see `hostvars` in playbooks).

## Requirements

- Debian-based OS
- Network connectivity to backend Cribl Edge nodes
- Ports 1514-1518, 2055 (syslog/NetFlow) and 8404 (HAProxy stats) available

## Role Variables

All variables in `defaults/main.yml` are user-configurable.

### Key Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `haproxy_service_state` | started | HAProxy service state |
| `haproxy_service_enabled` | true | Enable HAProxy on boot |
| `nginx_service_state` | started | Nginx service state |
| `nginx_service_enabled` | true | Enable Nginx on boot |
| `haproxy_listen_ports` | 1514-1518, 2055 | TCP frontend ports |
| `nginx_udp_ports` | 1514-1518, 2055 | UDP frontend ports |
| `haproxy_backends` | cribl-edge-* | Backend Cribl Edge nodes |
| `haproxy_stats_port` | 8404 | HAProxy admin interface |

## Examples

### Basic Deployment

```yaml
- name: Deploy load balancers
  hosts: haproxy_group
  roles:
    - haproxy
```

## Accessing Statistics

HAProxy statistics dashboard:

- URL: `http://<haproxy-ip>:<stats-port>/stats` (IP from OpenTofu
  inventory, port from `tofu_data.constants.service_ports.haproxy_stats`)
- Username: admin
- Password: (set via `HAPROXY_STATS_PASSWORD` environment variable)

## Load Balancing Behavior

### HAProxy (TCP/HTTP)

- Algorithm: round-robin
- Health checks: TCP port 1514, interval 5s, timeout 5s
- Persistence: None (stateless syslog)
- Protocol: TCP only

### Nginx Stream (UDP)

- Algorithm: round-robin (default)
- Health checks: None (UDP is stateless)
- Persistence: None
- Protocol: UDP only

## Tasks

- Install HAProxy and Nginx
- Generate HAProxy configuration (TCP/HTTP only)
- Generate Nginx stream configuration (UDP only)
- Configure frontend listening ports for both services
- Configure backend servers
- Ensure both services are running and enabled

## Handlers

- `reload haproxy`: Reload HAProxy configuration
- `reload nginx`: Reload Nginx configuration
