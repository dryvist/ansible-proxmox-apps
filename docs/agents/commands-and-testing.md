# Commands and testing

## Commands

> **Every converge runs through Semaphore.** Semaphore is the execution
> plane; its template wrapper loads the run environment from OpenBao before
> the playbook starts. Playbooks read plain environment variables and are
> independent of the secrets manager: `.env`, Doppler, OpenBao or any other
> injector behaves identically. `scripts/run-ansible.sh` remains the runner
> the wrapper calls and the break-glass path from a workstation. The commands
> below are that break-glass path, plus local development and testing.
>
> The OpenBao-node play (`--tags openbao` on `openbao_group`) is the single
> converge still run from a workstation under the secret-zero wrapper,
> because its inputs are the seal key and the provisioning identities. The
> AppRole TTL verification playbook (`verify-approle-ttls.yml`, below) runs
> through Semaphore like every other play — it is read-only against issued
> tokens and revokes everything it creates, so it carries none of the
> seal-key/provisioning-identity constraint that keeps the OpenBao-node play
> on a workstation.

```bash
# Deploy all apps (Doppler — main pipeline does not require SOPS)
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml

# Deploy all apps including SOPS-only roles (e.g., haproxy, mailpit)
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/site.yml'

# Deploy GitHub runners (requires token from gh-workflow-tokens Doppler project)
doppler run -p gh-workflow-tokens -c prd -- \
  doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/site.yml \
  --tags github_runner

# Edit encrypted secrets
sops secrets.enc.yaml

# Validate pipeline
doppler run -- ansible-playbook -i inventory/hosts.yml playbooks/validate-pipeline.yml

# Validate the whole *arr media stack via its APIs: indexer sync, download
# client safety flags (never auto-delete), qBittorrent killswitch-adjacent
# invariants (DHT/PEX/LSD off, narrow auth-bypass whitelist), media-management
# policy, root-folder <-> Plex library path consistency, and health (read-only,
# fails loud on any drift; a single failure never masks the rest of the report).
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/validate-media.yml'
# Scope to one app: --tags prowlarr|radarr|sonarr|qbittorrent|flaresolverr|plex|seerr|sortarr|consistency
# Add --tags deep to actively test each indexer against its tracker (slow, live)

# Re-trigger searches for pending monitored items (Sonarr + Radarr). Standalone,
# on-demand; never part of site.yml. Scope with --tags sonarr (or --tags radarr).
sops exec-env secrets.enc.yaml 'doppler run -- ansible-playbook \
  -i inventory/hosts.yml playbooks/search-missing.yml'

# Assert that issued AppRole tokens honour their declared bounds. Standalone,
# on-demand; never part of site.yml. Runs through its own Semaphore job like
# every other play; the command below is the local/on-demand form. Logs in
# with the AppRole credentials already in the environment, asserts each
# issued token's creation TTL against the declared one, and revokes every
# token it created. Roles with no ambient credentials are named in the
# output and are not covered by the run.
doppler run -- ansible-playbook playbooks/verify-approle-ttls.yml

# Lint
ansible-lint
```

> **`--limit` must include `localhost`.** The inventory loader
> (`inventory/load_tofu.yml`) runs on `hosts: localhost` and populates the
> dynamic inventory via `add_host`. Running with `--limit <group>` but **not**
> `localhost` silently skips the loader, so no hosts are added and every play
> reports "no hosts matched". Always use `--limit <group>,localhost`.
>
> **`scripts/run-ansible.sh` wraps `ansible-playbook` with a stale-checkout
> guard — the commands above call `ansible-playbook` directly and skip it.**
> The guard refuses to converge from a checkout behind its tracked branch (a
> stale checkout deploys old content and still exits 0 with a green play
> recap); `ALLOW_STALE_CHECKOUT=1` is the deliberate escape hatch for a
> pinned replay. It does **not** cover every stale-checkout case: a detached
> HEAD (CI's PR checkout, or a manual `git checkout <sha>`) has no tracked
> branch to compare against, so the guard skips the check there rather than
> failing — it does not, and structurally cannot, detect staleness on a
> detached checkout. Use `scripts/run-ansible.sh playbooks/site.yml ...`
> under an environment injector in place of the direct `ansible-playbook`
> calls above when checkout freshness matters.

## Execution Performance & Optimization

Since site playbook runs or dry-runs evaluate 55+ hosts, checks can take a
long time even when 99% of the tasks are no-ops (due to SSH/LXC connection
overhead and fact-gathering serialization).

To increase execution speed, you can leverage several options:

1. **Parallel Execution (`--forks` or `ANSIBLE_FORKS`)**: Increase the
   concurrency from the default 5 hosts at once. Using `25` forks
   (e.g. `doppler run -- ansible-playbook ... --forks 25`) runs significantly
   faster across large fleets.
2. **Targeted Runs (`--limit`)**: Keep play scope narrow by limiting execution
   to the specific role host and localhost (e.g., `--limit sortarr,localhost`).
3. **Scoping via Tags (`--tags`)**: Use `--tags <tag-name>` to run only a
   subset of roles (e.g., `--tags github_runner`).
4. **SSH Pipelining & Multiplexing**: Already enabled for SSH
   (`pipelining = True` and `ControlPersist=60s` in `ansible.cfg`).
5. **Disable Fact Gathering**: For ad-hoc plays where host facts are not
   needed, set `gather_facts: false` to skip the costly gathering step.

## Testing

### Fast (CI + pre-commit — runs automatically)

| Check | Command | When |
| --- | --- | --- |
| Ansible lint | `ansible-lint` | pre-commit, every PR |
| Playbook syntax | `ansible-playbook --syntax-check` | every PR (CI) |
| Inventory group validation | see below | every PR (CI) |
| Converge-telemetry contract | `python3 tests/test_converge_telemetry.py` | every PR (CI) |
| Molecule syntax | `molecule syntax` | every PR (CI, roles/molecule changes) |

**Inventory validation locally:**

```bash
TOFU_INVENTORY_PATH=$PWD/tests/inventory_load/tofu_inventory.json \
  ansible-playbook tests/inventory_load/verify_inventory.yml \
    -i inventory/hosts.yml -c local
```

### Extended (manual — run before merging role changes)

Full Molecule test deploys the `mssql_docker` role in a Docker container,
starts SQL Server, and verifies port 1433 is accepting connections.
Requires Docker on the local machine (~5-10 min).

```bash
# Install Ansible Galaxy dependencies (once)
ansible-galaxy install -r requirements.yml

# Run full test cycle (create -> converge -> idempotence -> verify -> destroy)
molecule test

# Or step through individually for debugging
molecule converge   # deploy role into container
molecule verify     # run assertions
molecule destroy    # clean up
```

**When to run:** Any time you modify a role in `roles/` before opening a PR.

### Reviewing a new check: which layer does it observe?

Ask one question of any check being added or changed: **does it observe the
layer that can actually break, or a layer upstream of it?** A check that reads
the wrong layer passes for the wrong reason, and a passing check nobody
questions is worse than no check at all.

Seams where this has bitten in practice:

| Check observes | What can still break |
| --- | --- |
| the evaluated config | whether the file reached disk |
| a file copied | whether the service parsed it |
| a command's exit code | whether it matched any hosts at all |
| a declared dependency | whether it is pinned |
| one platform | the platforms CI actually builds |
| a route responding | whether the payload was accepted |

Concrete shapes seen here: a play targeting a group nothing populates matches
zero hosts, warns once, and exits 0 having deployed nothing; a copied dashboard
reports `changed` whether or not the service could parse it; an HTTP endpoint
returns 200 to an empty body while rejecting every real payload.

Two habits that catch all of them:

- **Read the artifact back.** Query the service for what it loaded; re-fetch the
  object you wrote. An exit code describes the command, not the outcome.
- **Make failure loud.** `failed_when: false` and a permissive default turn a
  rejected request into a passing result — and an error body often maps cleanly
  over the same filters as a success body, so the output still looks plausible.

When a limit is exceeded, split the thing rather than raising the limit.
Raising it is always available and always looks reasonable, which is how a
limit stops being one.
