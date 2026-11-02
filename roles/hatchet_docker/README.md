# Hatchet Docker role

Runs the Hatchet dashboard and a full engine replica on each Docker AI guest
(`docker_ai_group`). Both guests share one PostgreSQL database for workflow
state and the Postgres-backed message queue.

## Shared state

- The database host is the writable apps PostgreSQL primary
  (`postgres_apps_primary_host`). Replicas are read-only, so Hatchet never
  points at one.
- Migration and the credential seed run once per converge, on the first guest.
- Both guests and the seed use the same cookie, encryption and JWT keysets.

## Publish the worker token

The worker token is stored at `secret/apps/hatchet/worker-token`. The publisher
token must be human-unlocked separately from the converge identity used by the
apps prefetch. This command keeps the publisher token in its dedicated
environment variable and lets `scripts/run-ansible.sh` provide the converge
identity as `BAO_TOKEN`:

```sh
openbao-unlock --via yubikey hatchet-token-publisher -- bash -c \
  'export HATCHET_TOKEN_PUBLISHER_BAO_TOKEN="$BAO_TOKEN"; unset BAO_TOKEN
   scripts/run-ansible.sh playbooks/site.yml --tags hatchet_worker_token \
     --limit docker_ai_group,localhost -e hatchet_docker_worker_token_publish=true'
```

The publish and worker deployment read the same OpenBao leaf with the converge
identity. A missing leaf triggers token minting; a denied read fails the run.

## Known single point of failure

The apps PostgreSQL primary is a single point of failure for Hatchet. Losing
one Hatchet guest is survivable: the other guest keeps serving. Losing the
primary stops scheduling on both guests until an operator fails over to a
replica, which is a manual step. After failover, converge this role so it
picks up the new primary.
