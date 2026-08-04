# opentofu_cli

Installs the OpenTofu CLI from the official OpenTofu apt repository on the
IaC execution host, so LAN-touching OpenTofu operations (`init` against the
remote backend, `plan`, state operations) run from a host on the network
instead of a workstation.

## Installation

The role lives in this repository under `roles/opentofu_cli/`. Reference it
from a playbook's `roles:` block — no Galaxy install needed:

```yaml
- hosts: docker_vms
  roles:
    - role: opentofu_cli
```

## API

The role adds two upstream signing keys to `/etc/apt/keyrings`, registers the
OpenTofu apt repository, and installs the `tofu` package. It configures no
credentials and writes no secret: backend coordinates and the API token are
supplied by the operator's environment at call time.

### Variables

See `defaults/main.yml` for the authoritative list.

- `opentofu_cli_host` (string, default `iac-platform`) — inventory name of
  the execution host. `playbooks/site.yml` gates the role on this so the CLI
  does not land on every Docker VM.
- `opentofu_cli_package_state` (string, default `present`) — passed through
  to `ansible.builtin.apt`. Use `latest` to track upstream releases.
- `opentofu_cli_keyring_dir`, `opentofu_cli_release_key_url`,
  `opentofu_cli_repo_key_url`, `opentofu_cli_repo_uri` — apt repository
  coordinates. Upstream requires two keys: the release key and the
  package-host key.

No version is pinned. The remote workspace declares the version it requires,
and a pin here would drift against it.

## Usage

Wired into `playbooks/site.yml` under the `opentofu_cli` tag:

```sh
ansible-playbook playbooks/site.yml --tags opentofu_cli
```

`--limit` is a silent no-op in this repository (hosts are added dynamically
by `inventory/load_tofu.yml`); run the tag against the whole site instead.

## Verification

```sh
tofu version
apt-cache policy tofu
```

## Idempotency

`get_url`, `apt_repository`, and `apt` are all idempotent; the version probe
is `changed_when: false`. A second run reports no changes.

## License

Internal — same license as this repository.
