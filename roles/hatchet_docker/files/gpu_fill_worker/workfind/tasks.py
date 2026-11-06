"""Register one serialized, nightly repository-workfinding task."""

from datetime import timedelta

from adapter import LatencyGuardError, run_chat
from workfind.agent import run_workfind


def workfind_slots(worker_config):
    return int("workfind" in worker_config)


def build_tasks(hatchet, worker_config, latency_guard=None):
    config = worker_config.get("workfind")
    if config is None:
        return []
    from hatchet_sdk import (
        ConcurrencyExpression,
        ConcurrencyLimitStrategy,
        Context,
        NonRetryableException,
        Priority,
    )

    platform = worker_config["platforms"][config["platform"]]
    role = config["llm_role"]
    role_limit = worker_config["roles"][role]["max_runs"]
    work_units = len(config["repos"]) * config["files_per_repo"]
    execution_timeout = timedelta(
        seconds=work_units * platform["timeout_s"] + len(config["repos"]) * 180 + 300
    )
    concurrency = ConcurrencyExpression(
        expression=f"'{role}'",
        max_runs=role_limit,
        limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
        name=f"gpu-{role.removeprefix('gpu-')}",
        is_tenant_scoped=True,
    )

    def handler(_input, _ctx: Context):
        try:
            return run_workfind(
                config,
                platform,
                chat=run_chat,
                latency_guard=latency_guard,
            )
        except LatencyGuardError:
            return {"status": "skipped", "reason": "latency_guard", "created": 0}
        except Exception as error:
            raise NonRetryableException(f"workfind failed: {type(error).__name__}") from None

    task = hatchet.task(
        name="gpu-repo-workfind",
        on_crons=[config["cron"]],
        concurrency=[concurrency],
        retries=0,
        execution_timeout=execution_timeout,
        default_priority=Priority.LOW,
    )(handler)
    return [task]
