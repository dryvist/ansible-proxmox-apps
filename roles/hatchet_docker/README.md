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

## Scheduled parse evaluation

Inventory configures 1 daily `eval-parse-small` run at `03:17` in Hatchet's
cron timezone. It stays gated by `hatchet_docker_eval_enabled: false`.
Enable it only after verifying the existing `vikunja-clerk-evals` Langfuse
dataset contains labeled parse requests and the `small` route and its
credential permit only local inference. Dataset provisioning is external
to this role; an absent dataset fails the run.

The existing worker evaluates the pinned Vikunja clerk parse prompt and
stores `expected-fields-match` and `parse-json-schema-valid` scores in the
Langfuse experiment `vikunja-clerk-evals-small`, with the prompt source
commit and model role. The named consumer is the Vikunja clerk maintainer:
review both scores and failed cases before promoting parser prompt or model
changes. This is a manual review input, not an automated promotion gate.

The workflow uses low Hatchet priority, inference priority `100`, a latency
guard, concurrency `1` per role across workers, and a `1`-hour execution
timeout. Latency holds have at most `6` retries with backoff capped at `300`
seconds; experiment failures are non-retryable. Judge sync remains
unscheduled, and `hatchet_docker_worker_fill_enabled` stays `false`.

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

## Release digest

The optional release digest is disabled by default. Enable
`hatchet_docker_worker_release_digest_enabled`, add `owner` and `repo` entries
for public GitHub repositories to `hatchet_docker_worker_release_digest_repositories`,
and optionally add an `interest_tag` to focus each local model summary. It runs
daily at `23 11 * * *` using the configured chat platform and posts one
risk-grouped Slack message only when a release was published in the prior 24 hours.
The webhook URL is
injected into `hatchet_docker_worker_release_digest_auth_env` from the existing
`platform_alerts_slack_webhook_key` in the `ntfy` secret domain.

## Known single point of failure

The apps PostgreSQL primary is a single point of failure for Hatchet. Losing
one Hatchet guest is survivable: the other guest keeps serving. Losing the
primary stops scheduling on both guests until an operator fails over to a
replica, which is a manual step. After failover, converge this role so it
picks up the new primary.
