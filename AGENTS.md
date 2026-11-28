---
skill-groups: [core, homelab]
---
# Ansible Proxmox Apps — AI Agent Documentation

Configure applications on Proxmox VMs and LXC containers.
VMs/containers are provisioned by `tofu-proxmox`;
this repo handles app config only.

## CI: Leak review gate (AI Merge Gate)

The `gate / Leak review` policy gate scans the PR diff with an LLM rubric
(`.ai-workflows/.github/` + `leak-prompt.yml` in the JacobPEvans/.github-ai
repo). Four categories: `credential`, `private_host_or_ip`,
`internal_topology`, `incident_detail`. Findings are advisory before
`LEAK_ADVISORY_END_DATE` and blocking on/after that date.

`internal_topology` = "the diff reveals the layout of private
infrastructure: which hosts exist, how they connect, what depends on what".
This is **diff-scoped but context-aware**: the LLM reads the whole repo
context, so a list of short internal names (e.g. role names already
declared in `roles/.../defaults/`) can be flagged when an accompanying
comment explains how they map to a private service layout ("one bot
user, token and share set per calling role ... login leaf in the
store"). Names alone without topology-explaining prose may pass or
fail depending on model version — treat the gate as non-deterministic.

Resolution patterns that have worked:
- Remove or rephrase the topology-explaining comment; keep the data
  lines. The LLM then typically stops flagging the list.
- Request the `leak-review-override` PR label (human action) only
  when the flagged content is intentionally part of the public diff
  (e.g. names that already exist in committed role defaults).

Do not "fix" the gate by weakening the rubric or the date.

## Container-runtime exceptions

Guests are system containers by default. These roles run Docker because the
vendor ships no other runnable form:

- `hatchet_docker`: Hatchet v0.114.2 ships only `hatchet-cli` as a native
  binary. The engine, API and Lite come only as container images or source,
  and nixpkgs has no package. Read 2026-11-01 from the
  [v0.114.2 release assets](https://github.com/hatchet-dev/hatchet/releases/tag/v0.114.2).
- `openhands`: vendor-shipped per-conversation containers.
- `unifi_insights_docker`: UniFi-Insights-Plus ships only a container image
  (`ghcr.io/jmasarweh/unifi-log-insight`) and no native package. Read
  2026-11-16 from the [v3.7.2 release](https://github.com/jmasarweh/UniFi-Insights-Plus/releases/tag/v3.7.2).

Full docs live under `docs/agents/`, one topic per page:

- [Repo ownership and pipeline data flow](docs/agents/repo-ownership.md) —
  what this repo owns (Cribl, HAProxy, DNS, notification services,
  the media stack, ...), the syslog/netflow pipeline, and prod-vs-test rules.
- [Inventory](docs/agents/inventory.md) — Nautobot as the system of record for
  infrastructure inventory (policy; nothing reads it yet), how `load_tofu.yml`
  resolves the dynamic inventory today, its groups, and every environment
  variable a role reads.
- [Secrets management](docs/agents/secrets.md) — at-rest encryption
  and where changes to the `openbao` role are made.
- [Commands and testing](docs/agents/commands-and-testing.md) — every
  `ansible-playbook` invocation this repo supports, performance tuning, and
  the fast/extended test tiers.
- [Dev environment and related repositories](docs/agents/dev-environment.md) —
  the Nix/direnv shell and how this repo relates to its peers.

## CI

Main-target pull requests and pushes to `main` run the full Molecule matrix,
required by `Merge Gate`. Develop pull requests and non-main pushes use the
shared changed-path selection; unmapped changes fail. An empty development
selection skips Molecule while the classifier and local contracts remain
required. Public pull-request CI stays on GitHub-hosted runners.

See the canonical policy in the `JacobPEvans/.github` README, “Ansible CI policy.”
