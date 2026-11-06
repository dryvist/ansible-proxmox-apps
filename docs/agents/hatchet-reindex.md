---
type: reference
title: Hatchet nightly reindex
description: Incremental public repository and memory export indexing.
---

Enable `hatchet_docker_worker_reindex_enabled` alongside the worker flag.
The low-priority, tenant-serialized task runs at `37 1 * * *` in Hatchet's
scheduler timezone. It uses router model `embed`; hardware placement belongs
to the router. No embedding model or GPU address is configured here.

Set `hatchet_docker_worker_reindex_repos` to a list of public HTTPS repository
URLs and destination `collection` names. Each run makes fresh shallow clones,
chunks text source files and documents using the existing fill chunker, and
skips hidden files, symlinks, binary content, and files over 1 MB.
Set `hatchet_docker_worker_reindex_qdrant_url` and provision the named Qdrant
collections with unnamed vectors matching router `embed` dimensions.
This checkout has no Weaviate role.

An optional `hatchet_docker_worker_reindex_hindsight_export` points to a host
JSON file mounted read-only. Supply a JSON array of objects with unique string
`id` and string `text` fields. The export producer owns refreshing this file;
replace its contents in place so the container bind mount sees updates.
Memories use `hatchet_docker_worker_reindex_hindsight_collection`.

The worker reads credentials from environment; Compose resolves the router
and database keys through the existing application-secret mapping. Secrets
are absent from worker configuration and results.

Stable point IDs and content hashes skip unchanged chunks. Confirmed writes
precede checkpoint replacement. Removed chunks are deleted only when owned
by this worker's checkpoint, after every source loads successfully. A failed
run leaves the previous checkpoint for idempotent replay. Keep the output
volume durable. Use a separate output directory for each independent worker
configuration. Changing the router's embedding model behind the same alias
requires removing the checkpoint and rebuilding compatible collections.

Set `hatchet_docker_worker_reindex_smoke_query` to enable a retrieval query
and router `rerank` call for each nonempty collection, including unchanged
collections. Empty disables smoke queries.

The output directory holds `checkpoint.json`, `results.json`, and
`reindex.prom`. Results and Prometheus text include changed, unchanged,
deleted, reranked, and duration measurements per collection, plus run status
and total duration. The same results are logged through `gpu_fill.reindex`.
The worker has no pre-existing metrics HTTP exporter; configure the metrics
collector to read the output file. No collector or live service is enabled by
this role's default configuration.

API contracts: [Qdrant upsert](https://api.qdrant.tech/api-reference/points/upsert-points)
and [LiteLLM proxy](https://docs.litellm.ai/api-reference).

Run fake-based tests with
`pytest -q tests/test_hatchet_gpu_fill_worker_reindex.py`.
