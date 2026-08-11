# Dev environment and related repositories

## Dev Environment

This repo uses [Nix flakes](https://wiki.nixos.org/wiki/Flakes) + [direnv](https://direnv.net/) for a reproducible dev environment.

### Activation

```sh
direnv allow    # one-time per worktree — auto-activates on cd
```

The shell is provided by the `ansible-apps` shell in
[nix-devenv](https://github.com/JacobPEvans/nix-devenv) via `.envrc`.
There is no local `flake.nix` — direnv fetches and caches the remote shell automatically.

To activate manually without direnv:

```sh
nix develop "github:JacobPEvans/nix-devenv#ansible-apps"
```

### Tools provided

- ansible, ansible-lint, molecule — configuration management
- sops, age — secrets management
- python3 with paramiko, pyyaml, jinja2, jsondiff — Ansible dependencies
- jq, yq, pre-commit — utilities

## Related Repositories

| Repo | Relationship |
| --- | --- |
| tofu-proxmox | Upstream: provisions VMs/containers |
| ansible-splunk | Peer: owns Splunk Enterprise deployment |
| ansible-proxmox | Peer: owns Proxmox host config (kernel, ZFS, firewall) |
| ansible-servarr | Consumed: the media stack, pinned as the `servarr/` submodule and converged by a final `site.yml` play |
| ansible-proxmox-ai | Peer: owns the AI/LLM roles split out in #996 (llm_router, hermes_agent, qdrant, ...) with its own site.yml/inventory loader |
