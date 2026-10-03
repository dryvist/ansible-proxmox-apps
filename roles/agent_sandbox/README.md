# agent_sandbox

Egress boundary for autonomous agent containers
([dryvist/nix-agent-sandbox](https://github.com/dryvist/nix-agent-sandbox))
on the `agent_sandbox_host` inventory group (`docker_vms` members carrying the
`agent-sandbox` tag):

- `agents` docker network with `internal: true` — members have **no route
  out**; Docker itself enforces the default-deny.
- A squid CONNECT proxy (`agent-squid`, alias `proxy:3128` on that network)
  is the sole dual-homed member; its domain allowlist is the only egress
  policy. Converge ends with live allow/deny probes from inside the network.
- A host nftables table (`agent_sandbox`, chain `DOCKER-USER`) drops every
  forwarded container packet that is not bound for the proxy or DNS, and any
  forwarding from the other container bridges, so a container that ignores
  its proxy settings still has no way out.
- `/var/lib/docker` sits on the guest's dedicated data disk.

Agent containers are **not** managed by Ansible: the nix-agent-sandbox
`agent run --host <docker-host>` launcher spawns them ad hoc with plain
`docker run --network agents` — no IaC run per container.

## Installation

Included via the `Deploy agent sandbox egress boundary` play in
`playbooks/site.yml` (hosts: `agent_sandbox_host`). Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags agent_sandbox --diff
```

## Usage

From a workstation with the nix-agent-sandbox CLI:

```sh
BAO_ADDR=https://openbao.<domain> \
  agent run --host <docker-host-fqdn> --profile dev \
  --repo dryvist/some-repo "task prompt"
```

The launcher attaches the container to `agents` and points
`HTTP(S)_PROXY` at `http://proxy:3128`; everything not on the allowlist is
denied by squid, and everything else has no route at all.

## Allowlist maintenance

`agent_sandbox_egress_domains` mirrors nix-agent-sandbox `lib.egressDomains`
(the source of truth). Regenerate after upstream changes:

```sh
nix eval github:dryvist/nix-agent-sandbox#lib.egressDomains --json
```

`agent_sandbox_internal_domains` appends in-network FQDNs (the OpenBao
ingress route) at converge time from ambient `PROXMOX_SUBDOMAIN` — the
sensitive domain is never committed.

## Session-log shipping

Agent containers are `--rm`, so their CLI session logs would die with the
container. `agent run --host` bind-mounts each run's per-CLI session-log subdir
under `{{ agent_sandbox_spool_dir }}/<run-id>/{claude,codex,gemini}/`, and this
role runs a **Cribl Edge container** (`agent-cribl-edge`) that tails the spool
and ships each run's session records to Splunk before teardown:

- Worker-level file inputs (one per CLI) with a 4 MiB newline breaker for the
  oversized session-log lines and per-CLI `datatype` metadata — the same shape
  as the Mac Edge (`dryvist/nix-darwin` `hosts/common/cribl.nix`).
- codex/gemini run their pack pipeline (`codex_sessions` / `llm_normalize`,
  installed verbatim from the released `.crbl`s); claude ships raw and is
  stamped Stream-side.
- Outputs are `tcpjson` to the HAProxy-fronted Stream per-CLI frontends
  (`agent_sandbox_cribl_ports`), with the persistent queue buffering across any
  downtime.

A daily `agent-sandbox-spool-prune.timer` drops whole runs older than
`agent_sandbox_spool_retention_days` (7). The launcher side (the bind mounts)
lives in `dryvist/nix-agent-sandbox`.

## Container-egress filter

`agent-sandbox.nft` is loaded by `agent-sandbox-nft.service` before the Docker
daemon starts and lives in its own table, so reloading it or restarting Docker
never touches any other rule. The chain hooks `forward` ahead of Docker's own
rules:

- established and related traffic is accepted;
- from the `agents` bridge: TCP to the proxy, and UDP/TCP 53 to the host
  resolver, are accepted; everything else is logged (rate-limited) and dropped;
- from `docker0` and any other `br-*` bridge except the proxy's egress bridge:
  dropped.

The converge asserts the table is loaded and probes a default-bridge container
for a route out.
