# traefik

HTTPS reverse-proxy / TLS ingress for **every** service web UI. Traefik runs as a
pinned static binary under systemd on the ingress LXC (`media_svc` VLAN)
and fronts each service at `https://<name>.{{ proxmox_domain }}` — no ports. It
fetches and **auto-renews a single wildcard `*.{{ proxmox_domain }}`** Let's
Encrypt certificate **itself** via the **Route53 DNS-01 challenge** (lego, built
into Traefik). DNS-01 needs no inbound internet, so purely-internal services still
get a valid public cert. It supersedes the legacy `nginx-proxy-manager` LXC.

`proxmox_domain` is `pve.<apex>` (the `PROXMOX_DOMAIN` env already set repo-wide),
so hostnames are e.g. `plex.pve.<apex>`, and the cert covers `*.pve.<apex>`.

## How it works

- **Static config** (`templates/traefik.yml.j2`) — `web`(:80)→`websecure`(:443)
  redirect, the `letsencrypt` resolver (`dnsChallenge.provider: route53`), the
  file provider watching `dynamic/`, secured API (`insecure: false`), TLS ≥1.2 +
  `sniStrict`.
- **Dynamic config** (`templates/dynamic.yml.j2`) — one router + service per entry
  in the tofu-owned ingress table `tofu_data.ingress` (`{name, ip, port}`).
  Every router requests the wildcard via `tls.domains`, so Traefik issues it once
  and serves it for all hosts.
- **Credentials** — the dedicated `acme` AWS user's keys are written to a
  **root-only `EnvironmentFile`** (`/etc/traefik/acme.env`, `0600`) consumed by the
  systemd unit; never in the world-readable config or on the process args. Setting
  `AWS_HOSTED_ZONE_ID` lets lego skip `ListHostedZonesByName` (tighter IAM).
- **Dashboard** — basicAuth reads an htpasswd `usersFile` the role **generates +
  persists on the host at build time** (`tasks/dashboard_auth.yml`). No credential
  is committed or placed in the rendered config; retrieve the generated password
  from `/etc/traefik/.dashboard_password` (root-only) on the ingress LXC.

## Prerequisites (Workstream 0 — one-time AWS + Doppler setup)

### 1. Least-privilege IAM policy for the `acme` user

Attach this to the dedicated AWS `acme` user. It is scoped to the **one**
`pve.<apex>` hosted zone and write-restricted to `_acme-challenge.*` **TXT**
records — it cannot touch A records or any other zone.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "GetChangeStatus", "Effect": "Allow",
      "Action": "route53:GetChange", "Resource": "arn:aws:route53:::change/*" },
    { "Sid": "ListRecordsInPveZone", "Effect": "Allow",
      "Action": "route53:ListResourceRecordSets",
      "Resource": "arn:aws:route53:::hostedzone/<PVE_ZONE_ID>" },
    { "Sid": "WriteAcmeChallengeTxtOnly", "Effect": "Allow",
      "Action": "route53:ChangeResourceRecordSets",
      "Resource": "arn:aws:route53:::hostedzone/<PVE_ZONE_ID>",
      "Condition": {
        "ForAllValues:StringLike":   { "route53:ChangeResourceRecordSetsNormalizedRecordNames": ["_acme-challenge.*"] },
        "ForAllValues:StringEquals": { "route53:ChangeResourceRecordSetsRecordTypes": ["TXT"] }
      } }
  ]
}
```

`<PVE_ZONE_ID>` is the existing `pve.<apex>` hosted-zone id (already in Doppler as
`ROUTE53_ZONE_ID`). Because the role sets `AWS_HOSTED_ZONE_ID`, the
`route53:ListHostedZonesByName` action is **not** needed; add
`{"Effect":"Allow","Action":"route53:ListHostedZonesByName","Resource":"*"}` only
if you stop providing the zone id.

### 2. Doppler secrets

| Secret | Purpose |
| --- | --- |
| `AWS_ACME_ACCESS_KEY_ID` | Dedicated `acme` user access key (DNS-01 only) |
| `AWS_ACME_SECRET_ACCESS_KEY` | Dedicated `acme` user secret |
| `ROUTE53_ZONE_ID` | **Reused** — the `pve.<apex>` zone id (already set by aws-infra) |
| `ACME_EMAIL` | (optional) mailbox for LE expiry notices; omitted from the config when unset |

Long-lived → Doppler (not SOPS), matching the repo convention for runtime creds.
The dashboard password is **generated on the host** (not a Doppler secret) — see
"Dashboard" above.

## Fronted services

The route list is **not** maintained in this role. It is the single tofu-owned
ingress table — `tofu-proxmox` `locals.tf` `ingress_services`, surfaced as
`ansible_inventory.ingress` and consumed here as `tofu_data.ingress`. The
`technitium_dns` role derives its DNS aliases from the **same** source, so a
fronted service is added/removed in exactly one place. Add it in tofu-proxmox.

- **Tier 1 — media stack** (same `media_svc` VLAN as Traefik): `plex`, `seerr`
  (→ `seerr` backend), `sonarr`, `radarr`, `qbittorrent`, `prowlarr`. Reachable
  at layer 2 — no UniFi rule, and **no killswitch change** (the qBittorrent/Prowlarr
  WebUIs are LAN-reachable; the killswitch governs egress only).
- **Tier 2 — infra UIs on other VLANs** (`technitium`, `pihole`, `phpipam`, `minio`,
  `mailpit`, `ntfy`, `homeassistant`, `openproject`, `prometheus`,
  `qdrant`, `haproxy-stats`): each needs a **UniFi inter-VLAN allow** (Traefik
  `media_svc` → target VLAN), enforced in `terraform-unifi`. Some apps also need
  their own reverse-proxy trust setting (e.g. **Home Assistant**
  `http.trusted_proxies` / `use_x_forwarded_for`) — in the app's config, not here.
- **Apex — Proxmox cluster UI** (the base domain itself, e.g.
  `pve.<domain>`, with no `<name>.` prefix): an `apex` + multi-backend ingress
  row that **load-balances across every commissioned node's web UI**
  (`https://<role>.<domain>:8006`) with a sticky session cookie + per-node health
  checks. Backends are node **FQDNs** (hostnames, not IPs) that already resolve
  internally; Traefik re-encrypts over HTTPS and skips verification via the
  shared `insecure-backend` transport (self-signed node certs). The apex is
  already a SAN on the wildcard cert, so no extra certificate work.

## Installation

Wired into `playbooks/site.yml` (`hosts: traefik_group`, tag `traefik`). The LXC
joins `traefik_group` automatically via its OpenTofu `traefik` tag. Collections
are installed once with `ansible-galaxy collection install -r requirements.yml`.

## Usage

```sh
sops exec-env secrets.enc.yaml 'doppler run -- \
  ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags traefik'
```

Pair with `--tags dns` so Technitium publishes the `<name> → traefik` CNAMEs:

```sh
sops exec-env secrets.enc.yaml 'doppler run -- \
  ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags traefik,dns'
```

Render-only (no live host) for config inspection:

```sh
ansible-playbook tests/template_render/verify_templates.yml -c local
```

## Verification

- `acme.json` (`0600`) receives a wildcard `*.pve.<apex>` cert (issuer Let's
  Encrypt) within minutes; the transient `_acme-challenge` TXT appears in Route53
  then clears.
- From a LAN client, `https://plex.pve.<apex>` (etc.) serves a valid cert with SAN
  `*.pve.<apex>`, proxies to the backend, no port. `curl -v` / `openssl s_client`.
- `traefik.pve.<apex>` → 401 without the dashboard basicAuth.

## Notes

- Plex: set its **Custom server access URL** to `https://plex.pve.<apex>` (the
  `plex` role does this idempotently). Traefik forwards `X-Forwarded-Proto: https`
  automatically; very long idle streams can be tuned later via a custom
  `serversTransport` if needed.
- The role is render-safe: with `traefik_manage_services: false` it renders all
  config but skips the binary download + systemd (used by the template-render test).
