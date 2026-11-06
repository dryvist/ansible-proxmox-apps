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

## Optional Splunk alert triage

Set `hatchet_docker_worker_splunktriage_enabled: true` with the worker enabled.
Configure `hatchet_docker_worker_splunktriage_splunk_url` (HTTPS management API)
and `hatchet_docker_worker_splunktriage_local_model_url` (direct private IP,
OpenAI-compatible `/v1` base URL serving the `medium` model). This endpoint must
serve the local RTX 6000 model directly, without provider fallback. DNS names
and public model IPs are rejected; redirects are refused.

The worker reads `SPLUNK_TOKEN`, `SPLUNKTRIAGE_MODEL_TOKEN`, and
`SPLUNKTRIAGE_SLACK_WEBHOOK` from its environment. Compose resolves their values
from the existing `bao_apps_secrets` keys `hatchet_splunktriage_splunk_token`,
`hatchet_splunktriage_model_token`, and `hatchet_splunktriage_slack_webhook`.
Rendered credentials use the deployment's existing `no_log` template task.

At minutes 03, 13, 23, 33, 43, and 53 (Hatchet schedule timezone), triage pages
through fired-alert groups and their occurrences since the last successful
checkpoint. The first run covers the preceding 10 minutes. Alerts must have
triggered-alert tracking enabled in Splunk. For each group, the newest
occurrence's drilldown search (or job event search) runs over the 5 minutes
ending at its trigger time, capped at 1000 results and 60 seconds of search
execution. Inline time terms, macros, subsearches, and unresolved tokens are
rejected to preserve the dispatch bounds.

Local inference drafts a short summary, likely cause, 3 event selections, and
the next search. Event quotes come from the retrieved results. The worker
includes drafted SPL only after `/services/search/parser` accepts it with
`parse_only=true`; disabled or unavailable parsers yield an explicit omission.
Drafted searches are never executed. One plain-text Slack message is posted
per group, without automatic link previews.

The persistent state mount stores occurrence fingerprints and a checkpoint,
not alert bodies. Confirmed groups survive retries; failures retain the
checkpoint. A crash after Slack accepts a message and before SQLite commits
can produce a duplicate because incoming webhooks have no idempotency key.
Only one triage task runs at a time. Private evidence stays out of Hatchet
results and error messages; Slack receives the requested summary and quotes.
