# agent_exec

Plain-LXC **Python runtime** for running [CrewAI](https://docs.crewai.com/) +
[LangChain](https://python.langchain.com/) agent code, with
[OpenLLMetry](https://github.com/traceloop/openllmetry) (OTLP/HTTP) tracing. No
Docker — just a venv and a systemd service.

This role ships the **platform** (runtime user, venv, instrumentation, unit); the
**agent code is user-supplied**. A placeholder `main.py` is deployed once and
idles so the first converge comes up green — replace it with your own agent.

## What it does

- Installs `python3` + `git` and creates a system user `agent-exec`
  (home `/var/lib/agent-exec`).
- Builds a venv at `/opt/agent-exec-venv` with `crewai`, `crewai-tools`,
  `langchain`, and the OpenTelemetry SDK + OpenLLMetry CrewAI/LangChain
  instrumentors.
- Deploys `otel_bootstrap.py` (Ansible-managed) — import it first from your
  entrypoint to wire spans to the OTLP/HTTP collector.
- Runs `main.py` under systemd (`Restart=on-failure`) with the `OTEL_*` env
  preset.

## Your agent code

Replace `/var/lib/agent-exec/main.py` (deployed `force: false`, never clobbered)
with your CrewAI/LangChain script. Keep `import otel_bootstrap` first so runs are
traced, then `sudo systemctl restart agent-exec`.

## Installation

This role ships with the repo; no separate install step and no collection
dependencies (plain LXC, no `community.docker`). Hosts follow the standard
selection: the `agent-exec`-tagged hosts from the terraform inventory are grouped
into `agent_exec_group` by `inventory/load_tofu.yml`, and the matching play in
`playbooks/site.yml` runs this role against them.

## Usage

Run via the standard site playbook (tag `agent_exec`):

```bash
ansible-playbook playbooks/site.yml --tags agent_exec
```

Or include the role directly against the group:

```yaml
- name: Provision the agent-exec runtime
  hosts: agent_exec_group
  become: true
  roles:
    - role: agent_exec
```

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `agent_exec_home` | `/var/lib/agent-exec` | runtime user home + working dir |
| `agent_exec_venv` | `/opt/agent-exec-venv` | Python venv |
| `agent_exec_pip_packages` | runtime + instrumentation | venv package set |

`ai_orchestration_otel_endpoint` (the OTLP collector base URL) is a group var
defined at the inventory level — this role consumes it, never defaults it.
