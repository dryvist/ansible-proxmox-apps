"""Opt-in nightly reindex task; SDK imports stay at the registration boundary."""

from datetime import timedelta

from .runner import run


def build_tasks(hatchet, worker_config):
    config = worker_config.get("reindex")
    if config is None:
        return []
    from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Priority

    def reindex(_input, _ctx):
        return run(config, latency_guard=worker_config.get("latency_guard"))

    return [hatchet.task(
        name="gpu-reindex",
        on_crons=["37 1 * * *"],
        concurrency=[ConcurrencyExpression(
            expression="'reindex'", max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
            name="gpu-reindex", is_tenant_scoped=True,
        )],
        retries=0,
        execution_timeout=timedelta(hours=6),
        default_priority=Priority.LOW,
    )(reindex)]
