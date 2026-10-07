---
skill-groups: [core, homelab]
---
# Ansible Proxmox Apps — AI Agent Documentation

Configure applications on Proxmox VMs and LXC containers.
VMs/containers are provisioned by `tofu-proxmox`;
this repo handles app config only.

Full docs live under `docs/agents/`, one topic per page:

- [Repo ownership and pipeline data flow](docs/agents/repo-ownership.md) —
  what this repo owns (Cribl, HAProxy, DNS, Authelia, notification services,
  the media stack, ...), the syslog/netflow pipeline, and prod-vs-test rules.
- [Inventory](docs/agents/inventory.md) — Nautobot as the system of record for
  infrastructure inventory (policy; nothing reads it yet), how `load_tofu.yml`
  resolves the dynamic inventory today, its groups, and every environment
  variable a role reads.
- [Secrets management](docs/agents/secrets.md) — at-rest encryption
  and the rule for changes to the `openbao` role.
- [Commands and testing](docs/agents/commands-and-testing.md) — every
  `ansible-playbook` invocation this repo supports, performance tuning, and
  the fast/extended test tiers.
- [Dev environment and related repositories](docs/agents/dev-environment.md) —
  the Nix/direnv shell and how this repo relates to its peers.

## CI

Pull requests into `develop` use changed-role Molecule selection with lint,
syntax, and contract checks. Pull requests into `main` and non-PR runs use the
full matrix. Required validation is aggregated by `Merge Gate`; shared or
unclassified changes widen to the full matrix. Public pull-request CI stays on
GitHub-hosted runners.

See the canonical policy in the `dryvist/.github` README, “Ansible CI policy.”
