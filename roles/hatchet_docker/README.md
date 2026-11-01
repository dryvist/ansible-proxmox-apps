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

## Known single point of failure

The apps PostgreSQL primary is a single point of failure for Hatchet. Losing
one Hatchet guest is survivable: the other guest keeps serving. Losing the
primary stops scheduling on both guests until an operator fails over to a
replica, which is a manual step. After failover, converge this role so it
picks up the new primary.
