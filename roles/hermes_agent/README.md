# hermes_agent

Deploys the **[NousResearch Hermes Agent](https://github.com/nousresearch/hermes-agent)**
— the self-improving **autonomous agent** — headless in a dedicated LXC on the AI
VLAN.

> This is **not** the `ollama` / `open_webui` (`hermes-infer` / `hermes-chat`) LLM
> *serving* stack. Those serve the Hermes-4 *model*; this role runs the *agent*,
> which uses that model (or any OpenAI-compatible endpoint) as its brain.

## What it does

- Installs Hermes Agent system-wide via the official installer (bundles Python/uv +
  Node), once, behind a `creates` guard. The installer is fetched from the pinned
  release tag's raw URL and **sha256-verified before it runs** — never
  `curl <url> | bash` of a moving remote script — and `--branch <tag>` pins the
  app checkout to the same release. The Hermes daemon owns subsequent updates
  (`hermes update`) — Ansible owns only the platform, so converge stays idempotent.
- Runs the `hermes gateway` daemon under a dedicated non-root `hermes` user via
  systemd. The gateway drives the built-in **cron** scheduler and the **Kanban**
  dispatcher (autonomy) even with no messaging platform configured.
- `HERMES_HOME` (`/var/lib/hermes/.hermes`) lives on a dedicated ZFS data volume —
  memory, skills, profiles, the Kanban DB, sessions and logs — so it is snapshotted
  and replicated pve→pve3 (the agent's accumulated knowledge is irreplaceable).
- Points the model backend at the LiteLLM router (`hermes-4-14b` via
  `llm.<subdomain>/v1`, OpenAI-compatible); sets memory provider to **Hindsight** (best self-hostable
  June 2026) alongside the always-on `MEMORY.md`/`USER.md`; caps `agent.max_turns`
  so a runaway loop can't pin the GPU overnight.

## Installation

This role ships in the `ansible-proxmox-apps` repository — no separate
installation. The role itself fetches and sha256-verifies the pinned Hermes
installer on the target, so the LXC only needs base connectivity and apt.

## Usage

Run the role against its inventory group:

```bash
doppler run -- uv run ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml \
  --tags hermes_agent
```

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `hermes_agent_home` | `/var/lib/hermes` | data-volume mount = the user home |
| `hermes_agent_model_base_url` | `https://llm.{{ PROXMOX_SUBDOMAIN }}/v1` (router) | the brain endpoint |
| `hermes_agent_model` | `hermes-4-14b` | model id |
| `hermes_agent_memory_provider` | `hindsight` | external memory provider |
| `hermes_agent_max_turns` | `90` | agentic-loop budget |

## Group / invocation

Targets `hermes_agent_group`, derived from the `hermes-agent` tag in `load_tofu.yml`.
Run via `site.yml` (`--tags hermes_agent`).

## Not yet live-validated

Verify on the first converge: (a) `install.sh` runs clean non-interactively as root
on a minimal Debian LXC; (b) `hermes gateway start` stays up headless with no
messaging platform; (c) Hindsight initialises from `config.yaml` alone (it may need
its client package on first run — `memory status` check is non-fatal so it surfaces
without failing the converge). Single-profile first; profiles + Kanban teams + a
messaging gateway are a documented follow-up (the whole `HERMES_HOME` is already
persisted for them).
