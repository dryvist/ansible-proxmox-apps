# download_vpn

VPN-locked downloader: **qBittorrent-nox + Prowlarr behind Proton WireGuard**
with a **fail-closed nftables killswitch**. If the VPN tunnel (`wg0`) is down
there is no route and no rule permitting non-VPN egress, so torrent and indexer
traffic is cut off instantly.

## Security model

The role is built so qBittorrent is *provably* unable to send/receive traffic
outside the VPN:

1. **nftables killswitch** — a single `inet` table with `output` policy `drop`.
   The only allowed egress is loopback, the LAN subnet (web UIs + *arr ⇄
   qBittorrent/Prowlarr), UDP to the Proton endpoint IP:port (handshake), and
   anything leaving via `wg0`. Covers IPv4 **and** IPv6.
2. **IPv6 killed at the kernel** — Proton is dual-stack. `sysctl
   net.ipv6.conf.{all,default,lo}.disable_ipv6=1` removes any IPv6 path; the
   `nft ip6` coverage is defense-in-depth.
3. **Interface binding** — qBittorrent's `Connection\Interface` and
   `Session\Interface` are pinned to `wg0`. Binding + killswitch = zero leaks
   (binding alone closed a 30% leak seen with the killswitch only).
4. **NAT-PMP port forwarding** — a systemd service loops `natpmpc` against the
   Proton gateway and pushes the assigned port into qBittorrent's listen port
   via the WebUI API.
5. **Boot-safe ordering** — qBittorrent/Prowlarr/NAT-PMP units
   `Requires=`/`After=`/`BindsTo=` the killswitch + `wg0` units, so they can
   never start (or stay up) without the lock.
6. **LAN web-UI reachability (reply-only)** — a connmark + dedicated routing
   table (`download-vpn-lanroute.service` + `templates/mangle.nft.j2`) let
   cross-subnet clients (e.g. the Traefik reverse proxy on the management VLAN)
   reach the qBittorrent/Prowlarr web UIs. Inbound UI connections are marked and
   only their **replies** are policy-routed back out the LAN NIC; app-initiated
   flows are never marked, so they still egress via `wg0` (or are dropped). This
   opens **no new egress path** — the killswitch guarantees above are unchanged,
   and the `ct mark` guard keeps WireGuard's own fwmark on encapsulated UDP
   intact so the tunnel is never recursively routed.

## Three validation layers (all mandatory)

- **CI** — `molecule/download_vpn/verify.yml`, on every PR. Asserts the nft
  DROP policy + only the allowed rules; qBittorrent interface == `wg0`; then
  simulates `wg0` down and asserts the netns has no v4/v6 internet egress.
- **Deploy-time** — `tasks/validate.yml`, imported at the role end so it runs
  on every play. Asserts the killswitch is active, internet-bound IPv4 traffic
  routes via `wg0` (wg-quick `Table = auto` keeps the main-table default on the
  LAN NIC and routes the tunnel through a separate fwmark table), no IPv6 default
  route exists, qBittorrent is bound to `wg0`, live VPN IPv4 egress works,
  forced non-VPN IPv4 + all IPv6 egress are refused, and the LAN-reply policy
  routing is present (web UIs reachable cross-subnet). **Fails the play on any
  violation.**
- **Runtime** — `download-vpn-validate.timer` (every ~2 min). Re-checks the
  above; on ANY breach it stops qBittorrent, alerts ntfy, and pings the
  healthchecks deadman. A stalled validator also pages (deadman semantics).

## Installation

Provisioned by the `download-vpn` LXC in `terraform-proxmox` (unprivileged,
`/dev/net/tun` passthrough, `nesting`/`keyctl`, `tank/downloads` + `tank/media`
bind-mounts). Deploy the role from this repo:

```bash
ansible-galaxy collection install -r requirements.yml
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml --tags download_vpn'
```

## Requirements

- Debian-based unprivileged LXC with `/dev/net/tun` and `nesting`/`keyctl`.
- Proton WireGuard config delivered via Doppler runtime env (variable names
  mirror the `.conf` `[Interface]`/`[Peer]` sections so a fresh Proton
  download maps 1:1): `PROTON_WG_IFACE_PRIVATE_KEY`,
  `PROTON_WG_IFACE_ADDRESS`, `PROTON_WG_PEER_PUBLIC_KEY`,
  `PROTON_WG_PEER_ENDPOINT`. Proton's tunnel DNS resolver `10.2.0.1` is a
  stable constant and is hardcoded in `defaults/main.yml` (not a secret).
  `QBITTORRENT_ADMIN_PASSWORD` is delivered via SOPS.
- `tank/downloads` + `tank/media` bind-mounted at `/mnt/downloads` and
  `/mnt/media`.

## Key variables

All ports/IPs come from OpenTofu (`tofu_data.constants.media_ports`,
derived LAN subnet) — nothing is hardcoded. See `defaults/main.yml`.

- `download_vpn_wg_endpoint` — Proton `host:port` (SOPS env).
- `download_vpn_lan_subnet` — LAN allowed through the killswitch (derived).
- `download_vpn_qbittorrent_web_port` — qBittorrent WebUI port (tofu).
- `download_vpn_qbittorrent_auth_whitelist` — CIDRs that skip WebUI auth
  (qBittorrent's `DisabledForLocalAddresses` analogue). Defaults to the `/16`
  supernet of `container_ip` (every homelab VLAN, derived — no hardcoded CIDR);
  narrow to `download_vpn_lan_subnet` for a tighter boundary.
- `download_vpn_prowlarr_web_port` — Prowlarr WebUI port (tofu).
- `download_vpn_validator_interval` — runtime validator cadence (default 2min).
- `download_vpn_ntfy_url` / `download_vpn_healthcheck_url` — breach alerting.

## Usage

```yaml
- name: Configure VPN-locked downloader
  hosts: download_vpn_group
  become: true
  roles:
    - role: download_vpn
```
