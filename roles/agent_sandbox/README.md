# agent_sandbox

Egress boundary for autonomous agent containers
([dryvist/nix-agent-sandbox](https://github.com/dryvist/nix-agent-sandbox))
on the docker-host VM:

- `agents` docker network with `internal: true` — members have **no route
  out**; Docker itself enforces the default-deny.
- A squid CONNECT proxy (`agent-squid`, alias `proxy:3128` on that network)
  is the sole dual-homed member; its domain allowlist is the only egress
  policy. Converge ends with live allow/deny probes from inside the network.

Agent containers are **not** managed by Ansible: the nix-agent-sandbox
`agent run --host <docker-host>` launcher spawns them ad hoc with plain
`docker run --network agents` — no IaC run per container.

## Installation

Included via the `Deploy agent sandbox egress boundary` play in
`playbooks/site.yml` (hosts: `docker_vms`). Converge just this role:

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

## Later hardening

Docker's `internal: true` is the enforcement point. If containers ever get
host networking or the compose definition drifts, host nftables rules
dropping forwarded traffic from the `agents` subnet (except to the proxy)
are the belt-and-braces follow-up; not implemented in v1.
