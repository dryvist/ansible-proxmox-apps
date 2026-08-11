# Ansible Proxmox Apps — AI Agent Documentation

Configure applications on Proxmox VMs and LXC containers.
VMs/containers are provisioned by `tofu-proxmox`;
this repo handles app config only.

Full docs live under `docs/agents/`, one topic per page:

- [Repo ownership and pipeline data flow](docs/agents/repo-ownership.md) —
  what this repo owns (Cribl, HAProxy, DNS, Authelia, notification services,
  the media stack, ...), the syslog/netflow pipeline, and prod-vs-test rules.
- [Inventory](docs/agents/inventory.md) — how `load_tofu.yml` resolves the
  dynamic inventory, its groups, and every environment variable a role reads.
- [Secrets management](docs/agents/secrets.md) — Doppler/SOPS runtime
  injection and the OpenBao plugins-first rule.
- [Commands and testing](docs/agents/commands-and-testing.md) — every
  `ansible-playbook` invocation this repo supports, performance tuning, and
  the fast/extended test tiers.
- [Dev environment and related repositories](docs/agents/dev-environment.md) —
  the Nix/direnv shell and how this repo relates to its peers.
