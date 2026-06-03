# Zot Registry Role

Installs and configures [Zot](https://zotregistry.dev), a lightweight
OCI-native container registry, on a Debian LXC. Zot serves two roles at once:

- **Pull-through cache** for the public registries (`docker.io`, `ghcr.io`,
  `quay.io`) via the `sync` extension with `onDemand` caching. The first pull
  of an image fetches it from upstream and caches it locally; subsequent pulls
  are served from local storage.
- **Private registry** for images built and pushed in the homelab. Pushed
  images live alongside the cached upstream content under
  `{{ zot_storage_dir }}`.

This unblocks firewalled Docker hosts (e.g. LXC containers with
`output_policy=DROP`) that cannot reach the internet directly: they point at
this registry as a `registry-mirror` and pull everything through it.

## Requirements

- Debian-based host (bookworm/trixie)
- Outbound internet access on the registry host (to reach the upstream
  registries it caches). The registry LXC runs with `output_policy=ACCEPT`.

## Role Variables

See `defaults/main.yml` for all variables.

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `zot_registry_version` | `v2.1.17` | Pinned project-zot/zot release tag |
| `zot_registry_port` | `5000` | HTTP listen port |
| `zot_registry_bind_address` | `0.0.0.0` | HTTP bind address |
| `zot_registry_storage_dir` | `/opt/zot/storage` | Image/blob storage (100G mount) |
| `zot_registry_config_dir` | `/etc/zot` | Config directory |
| `zot_registry_user` | `zot` | System user/group |
| `zot_registry_upstream_registries` | docker.io, ghcr.io, quay.io | Pull-through upstreams |

## Installation

Add the host to the `registry_group` (via the `registry` OpenTofu tag) and run
the deploy play in `playbooks/site.yml`, or apply the role directly:

```yaml
- name: Deploy Zot registry
  hosts: registry_group
  become: true
  roles:
    - zot_registry
```

## Usage

### Client Configuration (Docker mirror)

Firewalled Docker hosts pull through this registry. Configure their
`/etc/docker/daemon.json` (HTTP-only in v1, so the registry must be listed as
insecure):

```json
{
  "registry-mirrors": ["http://<registry-ip>:5000"],
  "insecure-registries": ["<registry-ip>:5000"]
}
```

Then `systemctl restart docker`. This is applied automatically by the
"Configure Docker registry mirror on LXC containers" play in
`playbooks/site.yml`.

### Pushing private images

```bash
docker tag myapp:latest <registry-ip>:5000/myapp:latest
docker push <registry-ip>:5000/myapp:latest
```

## TLS (follow-up)

v1 is **HTTP only** — no TLS. Clients must trust it via `insecure-registries`.
A follow-up should front Zot with TLS (HAProxy termination or native zot TLS
config under `http.tls`) and drop the insecure-registry client entries once a
trusted certificate is in place.

## Dependencies

None.

## License

Apache-2.0
