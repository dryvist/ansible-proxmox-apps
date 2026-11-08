# Hatchet Docker role

Runs the Hatchet dashboard and a full engine+API replica on each Docker AI
guest (`docker_ai_group`). The control plane is highly available: at least two
replicas sit behind the Traefik ingress pools, all sharing one PostgreSQL
database for workflow state and the Postgres-backed message queue.

Deploys only the dashboard and engine. Existing orphan containers and data
remain in place for separate decommissioning.

## HA topology

| Layer | Provider | Failover |
| --- | --- | --- |
| Engine + API | one full replica per `docker_ai_group` member (`SERVER_SERVICES: all`) | survivors keep serving; Traefik ejects the dead pool member |
| Ingress | tofu-owned `hatchet` (UI/API) and `hatchet-engine` (gRPC, h2c) routes | Traefik drops a backend once its health port stops answering |
| Workflow state | the shared apps PostgreSQL cluster | manual — flip one authority var, then converge (below) |
| Message queue | Postgres-backed (`SERVER_MSGQUEUE_KIND: postgres`) | same cluster as workflow state |

Health checks live at every layer: compose healthchecks probe the dashboard
API and the engine health endpoint, the converge waits for `/api/ready` and
`/ready` on every replica, and the ingress rows carry `health_check: true` so
Traefik routes only to replicas that answer.

## Replica topology

Replicas and hosts are parameters, never literals in the role:

- `hatchet_docker_control_plane_group` (default `docker_ai_group`) — the
  inventory group holding the control plane. tofu-proxmox tags guests
  `docker-ai`; `load_tofu` builds the group from that tag, so a replica is
  added or removed in deployment.json alone.
- `hatchet_docker_min_replicas` (default `2`) — the converge refuses to deploy
  below this floor, so a degraded group fails the run instead of silently
  un-HA-ing the control plane.
- Migration and the credential seed stay `run_once` no matter how many
  replicas exist.

## Ingress requirements (tofu-proxmox)

The role reads the published ingress table (`tofu_data.ingress`) and reports
whether each route is HA-ready; it never edits it. HA needs tofu-proxmox's
`ingress.tf` to publish:

- a `hatchet` route whose `backends` pool lists every docker-ai guest, with
  `health_check: true` against the dashboard's web port;
- a `hatchet-engine` route whose `backends` pool lists every docker-ai guest,
  `scheme: h2c`, and `health_check: true` with the engine health port as
  `health_check_port`.

Until both rows are pools, every converge names the gap. Task workers dial the
engine broadcast address (`hatchet-engine.<subdomain>:443`), so the gRPC pool
is what load-balances execution across engines.

## Failover test (kill test A)

`playbooks/hatchet-killtest.yml` hard-stops the first guest tagged
`hatchet-killtest`, requires the other tagged guest to keep answering `/ready`
while the engine takes over, then always starts the stopped guest again. Run
it directly (not part of site.yml):

    ansible-playbook -i inventory/hosts.yml playbooks/hatchet-killtest.yml

It derives its targets from the published inventory and reads its PVE power
token through the Semaphore AppRole login; caller-supplied values are refused.
Kill test A covers guest loss only — the database failover below is a separate,
operator-owned step.

### Failing over the database

The apps PostgreSQL primary is a single point of failure for Hatchet. Losing
one Hatchet guest is survivable: the other guest keeps serving. Losing the
primary stops scheduling on both guests until an operator fails over to a
replica: flip `postgres_apps_primary_host` (the one apps-tier routing
authority in `inventory/group_vars/all.yml`) to the promoted replica, then
converge this role so it picks up the new primary. Replicas are read-only, so
Hatchet never points at one by accident.

## Shared state

- The database host is the writable apps PostgreSQL primary
  (`postgres_apps_primary_host`). Replicas are read-only, so Hatchet never
  points at one.
- Migration and the credential seed run once per converge, on the first guest.
- Both guests and the seed use the same cookie, encryption and JWT keysets.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `hatchet_docker_min_replicas` | `2` | Replica floor the converge asserts |
| `hatchet_docker_control_plane_group` | `docker_ai_group` | Inventory group holding the replicas |
| `hatchet_docker_ingress_*` | derived from `tofu_data.ingress` | Published UI/API and gRPC routes and their backend pools |
