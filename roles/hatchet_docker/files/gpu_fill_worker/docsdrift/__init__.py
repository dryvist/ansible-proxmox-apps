"""Weekly documentation drift task registration."""

from datetime import timedelta

from docsdrift.sweep import sweep


def build_tasks(hatchet, worker_config):
    config = worker_config.get("docsdrift")
    if config is None:
        return []
    from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Priority

    def run(_input, _ctx):
        return sweep(config, worker_config["platforms"][config["platform"]],
                     worker_config.get("latency_guard"))

    return [hatchet.task(
        name="gpu-docsdrift", on_crons=["41 5 * * 0"], retries=0,
        concurrency=[ConcurrencyExpression(
            expression="'docsdrift'", max_runs=1, name="gpu-docsdrift",
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN, is_tenant_scoped=True,
        )], execution_timeout=timedelta(hours=6), default_priority=Priority.LOW,
    )(run)]
