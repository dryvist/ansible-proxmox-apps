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

## Nightly RAG evaluation

`hatchet_docker_worker_rageval_enabled` enables both the existing Q&A fill
generator and its 04:29 Hatchet evaluation. Fill output from the rolling 24
hours is queried against Hindsight and each configured vector endpoint. The
worker uses the mapped local chat route as the judge, writes aggregate JSON
metrics under `hatchet_docker_worker_rageval_results_dir`, and sends one Slack
summary per run. Reports omit questions, answers, retrieved passages, URLs,
and credentials.

Set the following variables in the Ansible controller environment when enabling
the flag. The role passes them into the worker container through its protected
Compose file:

| Variable | Use |
| --- | --- |
| `RAGEVAL_HINDSIGHT_RECALL_URL` | Full Hindsight bank recall URL; required |
| `RAGEVAL_HINDSIGHT_API_KEY` | Hindsight bearer key; required |
| `RAGEVAL_LLAMA_INDEX_QUERY_URL` | Optional LlamaIndex query endpoint (`text` and `similarity_top_k` query parameters) |
| `RAGEVAL_LLAMA_INDEX_API_KEY` | Optional LlamaIndex bearer key |
| `RAGEVAL_QDRANT_QUERY_URL` | Optional Qdrant points/query URL configured for text inference |
| `RAGEVAL_QDRANT_API_KEY` | Optional Qdrant API key |
| `RAGEVAL_QDRANT_MODEL` | Required when the Qdrant endpoint is configured |
| `RAGEVAL_SLACK_WEBHOOK_URL` | HTTPS incoming webhook; required |

The Hindsight URL targets its `memories/recall` API. Qdrant uses the text
inference query shape with `limit` set to `k`; LlamaIndex receives the question
as `text` and `k` as `similarity_top_k`, and must return `source_nodes` or
`sources` so the judge can inspect evidence. Qdrant payloads must include text.
[Hindsight recall API](https://docs.hindsight.vectorize.io/api-reference/recall-memories/),
[Qdrant text inference](https://qdrant.tech/documentation/embeddings/qdrant-cloud-inference/),
[LlamaIndex query endpoint example](https://developers.llamaindex.ai/python/framework/understanding/putting_it_all_together/apps/fullstack_app_guide/).

## Known single point of failure

The apps PostgreSQL primary is a single point of failure for Hatchet. Losing
one Hatchet guest is survivable: the other guest keeps serving. Losing the
primary stops scheduling on both guests until an operator fails over to a
replica, which is a manual step. After failover, converge this role so it
picks up the new primary.
