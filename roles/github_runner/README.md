# github_runner

Ephemeral, org-scoped GitHub Actions runner pools on the `docker_vms` guests.
One systemd template unit per slot (`github-runner@N.service`), one container
per job (`docker run --rm`, `EPHEMERAL=true`), one OpenBao Agent per host
minting the registration tokens — Ansible never renders a GitHub token.

## Pools

A host can run four kinds of pool. All of them are declared per host or host
group, never per repository; the labels decide which jobs land where.

| Kind | Selector | Defaults | Labels | Docker socket |
| --- | --- | --- | --- | --- |
| Main | `github_runner_org`, `github_runner_replicas`, `github_runner_group` | — | common + `github_runner_labels_pool` | yes |
| Review | `github_runner_review_orgs` (list of `{org, replicas, group}`) | replicas 2, group `pr-agent` | common minus `self-hosted` + `review` | no |
| General extra-org | `github_runner_extra_orgs` (list of `{org, replicas, group}`) | replicas 1, group `Default` | common + `github_runner_labels_pool` (as the main pool) | yes |
| Heavy | `github_runner_heavy_pool_enabled` + `*_heavy_pool_*` | 1 replica, label `heavy` | common + heavy label instead of the pool label | yes |

- **Main** — the org-level pool. Its runner group must allow all repositories
  and public repositories; keep repository names out of the inventory.
- **Review** — a dedicated lane for AI-review jobs. The first
  `github_runner_review_slots` main-pool slots on a host can also carry the
  `review` label; per-org review pools are separate unit sets
  (`github-runner-review-<org>@.service`).
- **General extra-org** — general runners for OTHER organizations whose
  public repositories ask for `runs-on: self-hosted`, which the review pools
  cannot serve (restricted group, no `self-hosted` label). Each slot
  registers with the main pool's labels into that org's group. Unit set:
  `github-runner-general-<org>@.service`.
- **Heavy** — an opt-in per-host pool for oversized CI jobs.

The per-org pools (review and general extra-org) share one machinery:
`tasks/pools.yml` validates both lists (unique orgs, distinct from
`github_runner_org`), tags each entry with its `kind`, and
`tasks/deploy_pool.yml` / `tasks/reconcile_pool_units.yml` deploy and
reconcile every selected pool the same way. Only the labels, mounts, default
replicas and default runner group differ by kind. Every pool organization can
also mint from its own registration set by listing it in
`github_runner_register_owners`; every other pool uses the shared
`github_runner_review_token_path` with an `org_name` parameter.

## Operational gates

- `tasks/validate_pool_limits.yml` sums every pool's `--cpus`/`--memory`
  demand and fails the converge before anything is restarted when it would
  overcommit the host.
- `tasks/container_audit.yml` (tag `runner_container_audit`) reads back every
  container and asserts no review runner got the Docker socket or an added
  group, and no container named `seerr-*` runs here.
- `github_runner_replicas: 0` is the teardown state: units are stopped and
  deregistered, and the token agent is stopped last (a stop must still be
  able to deregister).

## Inputs

`inventory/group_vars/docker_vms.yml` reads both pool lists from the OpenBao
platform env document (`GITHUB_RUNNER_REVIEW_ORGS`,
`GITHUB_RUNNER_EXTRA_ORGS`); organization names never enter the public
inventory. See `docs/agents/` for the inventory, secrets and testing docs.
