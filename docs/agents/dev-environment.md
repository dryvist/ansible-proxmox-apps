# Dev environment and related repositories

## Dev Environment

This repo uses [Nix flakes](https://wiki.nixos.org/wiki/Flakes) + [direnv](https://direnv.net/) for a reproducible dev environment.

### Activation

```sh
direnv allow    # one-time per worktree — auto-activates on cd
```

The local `flake.nix` re-exports the `ansible-apps` shell from
[nix-devenv](https://github.com/JacobPEvans/nix-devenv). `flake.lock` pins
that shell revision and its Nixpkgs dependencies; Renovate updates the lock.
The controller Python environment includes `hvac`, required by
`community.hashi_vault` tasks in the inventory resolver.

To activate manually without direnv:

```sh
nix develop .
```

### Tools provided

- ansible, ansible-lint, molecule — configuration management
- sops, age — secrets management
- python3 with paramiko, pyyaml, jinja2, jsondiff, boto3, botocore, and hvac — Ansible dependencies
- jq, yq, pre-commit — utilities

## Related Repositories

| Repo | Relationship |
| --- | --- |
| tofu-proxmox | Upstream: provisions VMs/containers |
| ansible-splunk | Peer: owns Splunk Enterprise deployment |
| ansible-proxmox | Peer: owns Proxmox host config (kernel, ZFS, firewall) |
| the media-stack repo | Consumed: pinned as the `servarr/` submodule and converged by a final `site.yml` play |
| ansible-proxmox-ai | Peer: owns the AI/LLM roles split out in #996 (llm_router, hermes_agent, qdrant, ...) with its own site.yml/inventory loader |
