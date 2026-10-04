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
  forwarded packet that leaves the agents bridge except traffic to the proxy,
  allows the published Web port only from inventoried Traefik addresses, and
  denies other forwarding into the bridge. Docker allocates container addresses.
- `/var/lib/docker` sits on the guest's dedicated data disk.
- The always-on ZCode Web/Server container uses the published multi-architecture
  image digest, runs as uid 1000 with a read-only root filesystem, and stores
  Web state and workspaces on persistent host directories. Its service
  credentials are supplied separately in a root-owned file readable by a
  dedicated secret group; this role only mounts that file read-only.

Ephemeral agent CLI containers are **not** managed by Ansible: the
nix-agent-sandbox `agent run --host <docker-host>` launcher spawns them with
plain `docker run --network agents` — no Ansible run per task. The persistent
ZCode Web service below is managed by this role.

## Installation

Included via the `Deploy agent sandbox egress boundary` play in
`playbooks/site.yml` (hosts: `agent_sandbox_host`). Converge just this role:

```sh
ansible-playbook playbooks/site.yml --tags agent_sandbox --diff
```

## Usage

From a workstation with the nix-agent-sandbox CLI. The variables a
`--profile` names are read from the caller's environment; `--repo` uses
`GH_TOKEN`, or the token `$AGENT_GH_TOKEN_CMD owner/name` prints:

```sh
AGENT_GH_TOKEN_CMD=./mint-repo-token \
  agent run --host <docker-host-fqdn> --profile dev \
  --repo dryvist/some-repo "task prompt"
```

The launcher attaches the container to `agents` and points
`HTTP(S)_PROXY` at `http://proxy:3128`; everything not on the allowlist is
denied by squid, and everything else has no route at all.

The ZCode Web service uses the same `agents` network and proxy. It binds port
443 on the address supplied by the dynamic inventory and accepts forwarded
Web traffic only from `traefik_group`. The SSO-gated `zcode` ingress row is
owned by OpenTofu's ingress table, which also supplies Traefik and DNS.

## Allowlist maintenance

`agent_sandbox_egress_domains` mirrors nix-agent-sandbox `lib.egressDomains`
(the source of truth). Regenerate after upstream changes:

```sh
nix eval github:dryvist/nix-agent-sandbox#lib.egressDomains --json
```

The host dispatcher completes host-side setup before creating an agent
container. Those host-only endpoints are not part of the container-facing
squid allowlist.

The ZCode service mounts its credential file read-only. This role manages and
validates the mount boundary; credential values remain outside the repository.

## Optional ZCode queue feeder

The host queue feeder is disabled by default. When enabled, it accepts only
unfinished tasks with the `zcode` label and a schema-1 JSON manifest declaring
`tool: zcode`, `kind: coding` or `review`, `sensitive: false`, an approved
`owner/repository`, and a bounded non-empty prompt. The repository allowlist
must be set explicitly; an empty or invalid manifest never starts a job.

The feeder assigns the selected task, writes a durable launch record before
starting the pinned host dispatcher, and serializes polls with a local lock. A
launch interrupted before its job id is recorded is marked for manual
reconciliation and is never started a second time automatically. Terminal
results are added to the original task as the six-line job/tool/repo/state/PR/
duration comment. Existing comments are checked after a lost response, so a
retry does not post a duplicate; the task is closed only after the comment is
confirmed. The dispatcher creates draft PRs; this feeder does not merge them.
Its job image uses the same immutable digest as the Web service.

## Session-log shipping

Agent containers are `--rm`, so their CLI session logs would die with the
container. `agent run --host` bind-mounts each run's per-CLI session-log subdir
under `{{ agent_sandbox_spool_dir }}/<run-id>/{claude,codex,gemini,zcode}/`, and this
role runs a **Cribl Edge container** (`agent-cribl-edge`) that tails the spool
and ships each run's session records to Splunk before teardown:

- Worker-level file inputs with a 4 MiB newline breaker for oversized records
  and per-CLI metadata — the same shape as the Mac Edge
  (`dryvist/nix-darwin` `hosts/common/cribl.nix`).
- codex/gemini run their pack pipeline (`codex_sessions` / `llm_normalize`,
  installed verbatim from the released `.crbl`s); claude ships raw to its
  per-CLI Stream input.
- ZCode CLI JSONL events are stamped `index=llm`, `sourcetype=zcode:cli`, and
  sent to Stream's generic S2S input.
- Outputs are `tcpjson` with persistent queues; per-CLI sources use the
  HAProxy-fronted Stream ports in `agent_sandbox_cribl_ports`, and ZCode uses
  the shared S2S port from Tofu constants.

A daily `agent-sandbox-spool-prune.timer` drops whole runs older than
`agent_sandbox_spool_retention_days` (7). The launcher side (the bind mounts)
lives in `dryvist/nix-agent-sandbox`.

## Container-egress filter

`agent-sandbox.nft` is loaded by `agent-sandbox-nft.service` before the Docker
daemon starts and lives in its own table, so reloading it or restarting Docker
never touches any other rule. The chain hooks `forward` ahead of Docker's own
rules:

- established and related traffic is accepted;
- from the `agents` bridge: TCP to the proxy is accepted; everything else is
  logged (rate-limited) and dropped;
- the published ZCode Web port is accepted only from inventoried Traefik
  addresses after Docker's expected DNAT mapping;
- from `docker0` and any other `br-*` bridge except the proxy's egress bridge:
  dropped.

The converge asserts the table is loaded and probes a default-bridge container
for a route out. To verify host-side HTTPS reachability and exercise the
`agents`-bridge drop counter with a routed, disposable container, run the
opt-in probe after deployment:

```sh
ansible-playbook playbooks/site.yml \
  --tags agent_sandbox,agent_sandbox_probe
```

The probe does not alter the nftables rules. It attaches one throwaway test
container to both sandbox networks, routes one external packet through the
`agents` bridge, checks that the packet fails and the matching drop counter
increases, then removes the container.
