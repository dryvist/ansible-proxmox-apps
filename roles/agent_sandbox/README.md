# agent_sandbox

Egress boundary for autonomous agent containers
([dryvist/nix-agent-sandbox](https://github.com/dryvist/nix-agent-sandbox))
on the `agent_sandbox_host` inventory group (`docker_vms` members carrying the
`agent-sandbox` tag):

- `agents` docker network with `internal: true` — members have **no route
  out**; Docker itself enforces the default-deny.
- A squid CONNECT proxy (`agent-squid`, alias `proxy:3128` on that network)
  is the sole dual-homed member; its domain allowlist is the only egress
  policy. The static list is managed by Ansible; the separate operator list at
  `/etc/agent-sandbox/allowed-domains.d/operator.txt` survives converges and is
  reloaded by Squid when an operator changes it.
- A host nftables table (`agent_sandbox`, chain `DOCKER-USER`) drops every
  forwarded packet that leaves the agents bridge except traffic to the proxy,
  allows the published Web port only from inventoried Traefik addresses, and
  denies other forwarding into the bridge. The proxy egress bridge permits
  HTTPS; Squid's static and operator domain lists select destinations. Docker
  allocates container addresses.
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
nix eval "github:dryvist/nix-agent-sandbox?ref=vN#lib.egressDomains" --json
```

The host dispatcher completes host-side setup before creating an agent
container. The router endpoint and the role-configured OpenBao FQDN are in the
static Squid allowlist; the operator list cannot add or remove OpenBao.

The ZCode service mounts its credential file read-only. This role manages and
validates the mount boundary; credential values remain outside the repository.

## Host dispatcher

With `agent_sandbox_dispatch_access_enabled`, the role installs the dispatcher
(`agent-dispatch`) and its SSH entry point (`agent-dispatch-ssh`) from one
pinned nix-agent-sandbox commit, each checked against its SHA-256. It also
installs the task profiles baked into the pinned job image and a root-owned
profile with the job image, the OpenBao address, the router endpoint and the
results project. The `agent-dispatch` account accepts only keys listed in
`agent_sandbox_dispatch_authorized_keys`, each restricted to the forced
command. A terminal session (`ssh -t`, verb `tty`) gets a PTY; nothing else
does.

The operator allowlist has a separate SSH identity. Set
`agent_sandbox_allow_access_enabled` and provide its public key in
`agent_sandbox_allow_authorized_keys`; it does not use the dispatcher job key.
The workstation `agent-allow` command supports `add`, `rm`, and `ls`. Changes
replace the operator list atomically, reload Squid, and append a timestamped
state record under `agent_sandbox_allowlist_log_file`.

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
- the proxy egress bridge may send HTTPS requests to the Squid allowlist;
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

## CI resolver

When `agent_sandbox_ci_resolver_enabled` is true, `ci-resolver.service` checks
failed CI runs and sends eligible fixes to the host dispatcher. An hourly timer
refreshes the workbook checkout, and a daily timer learns from completed fixes
and opens a workbook pull request. The feature is off by default and starts in
shadow mode.

| Variable | What it does |
| --- | --- |
| `agent_sandbox_ci_resolver_enabled` | Installs and starts the resolver when true; the default is false. |
| `agent_sandbox_ci_resolver_shadow` | Keeps the resolver in shadow mode when true; the default is true. |
| `agent_sandbox_ci_resolver_app_id` | Identifies the GitHub App used by the resolver. |
| `agent_sandbox_ci_resolver_github_mount` | Selects the OpenBao GitHub mount that issues tokens. |
| `agent_sandbox_ci_resolver_permission_set` | Selects the stored permission set requested for each token. |
| `agent_sandbox_ci_resolver_approle_dir` | Stores the resolver's dedicated AppRole files for its service account. |
| `agent_sandbox_ci_resolver_role_id` | Supplies the resolver AppRole role ID from the platform environment document. |
| `agent_sandbox_ci_resolver_secret_id` | Supplies the resolver AppRole secret ID from the platform environment document. |
| `agent_sandbox_ci_resolver_repos` | Lists repositories the resolver checks for failed runs. |
| `agent_sandbox_ci_resolver_max_attempts` | Limits attempts to resolve each failure. |
| `agent_sandbox_ci_resolver_vikunja_project` | Selects the Vikunja project that receives resolver results. |
| `agent_sandbox_ci_resolver_zammad_group` | Selects the Zammad group that receives resolver reports. |
