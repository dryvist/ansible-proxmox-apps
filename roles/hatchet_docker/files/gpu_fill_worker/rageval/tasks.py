"""Hatchet registration for the nightly RAG evaluation."""

from datetime import timedelta

from adapter import LatencyGuardError
from rageval.runner import run_rageval


def build_tasks(hatchet, worker_config, latency_guard=None):
    from hatchet_sdk import (
        ConcurrencyExpression,
        ConcurrencyLimitStrategy,
        Context,
        NonRetryableException,
        Priority,
    )

    rageval = worker_config["rageval"]

    def evaluate(_input, _ctx: Context):
        try:
            return run_rageval(worker_config, latency_guard=latency_guard)
        except LatencyGuardError:
            return {"status": "paused", "reason": "latency_guard"}
        except Exception:
            raise NonRetryableException("RAG evaluation failed") from None

    concurrency = ConcurrencyExpression(
        expression="'rageval'",
        max_runs=1,
        limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        name="gpu-rageval-nightly",
        is_tenant_scoped=True,
    )
    return [
        hatchet.task(
            name="gpu-rageval-nightly",
            on_crons=[rageval["cron"]],
            concurrency=[concurrency],
            retries=0,
            execution_timeout=timedelta(hours=6),
            default_priority=Priority.LOW,
        )(evaluate)
    ]
