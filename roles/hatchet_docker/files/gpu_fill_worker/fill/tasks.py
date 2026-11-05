"""Build the Q&A fill tasks and their per-role cron top-up tasks.

Every SDK import happens inside a function, so this module imports without hatchet_sdk installed.
"""

import logging
from datetime import datetime, timedelta, timezone

from adapter import LatencyGuardError, run_chat
from fill.corpus import ChunkPicker, load_chunks
from fill.qa import JsonlWriter, run_fill

RUN_TAG = "gpu_fill_role"
# A fill run that is still live is queued for at most SCHEDULE_TIMEOUT, then runs for at most its
# execution_timeout. The active window covers both plus a margin, and stays inside runs.list's range.
SCHEDULE_TIMEOUT = timedelta(minutes=10)
ACTIVE_MARGIN = timedelta(minutes=5)
logger = logging.getLogger("gpu_fill.tasks")


def top_up_count(max_runs, in_flight):
    """Runs to enqueue so that queued plus running fill runs for one role never exceed max_runs."""
    if type(max_runs) is not int or max_runs < 1:
        raise ValueError("max_runs must be a positive integer")
    return max(0, max_runs - max(0, in_flight))


def fill_slots(worker_config):
    """One worker slot per fill cron task. Fill runs share the agent slots through the role cap."""
    fill = worker_config.get("fill")
    return len(fill["roles"]) if fill else 0


def _make_top_up(hatchet, fill_task, role, max_runs, active_window):
    from hatchet_sdk import V1TaskStatus

    def top_up(_input, _ctx):
        now = datetime.now(timezone.utc)
        active = hatchet.runs.list(
            since=now - active_window,
            only_tasks=True,
            limit=max_runs,
            statuses=[V1TaskStatus.QUEUED, V1TaskStatus.RUNNING],
            additional_metadata={RUN_TAG: role},
            include_payloads=False,
        )
        in_flight = len(active.rows)
        count = top_up_count(max_runs, in_flight)
        if count:
            items = [
                fill_task.create_bulk_run_item(
                    input={"llm_role": role}, additional_metadata={RUN_TAG: role}
                )
                for _ in range(count)
            ]
            fill_task.run_many(items, wait_for_result=False)
        return {"llm_role": role, "in_flight": in_flight, "enqueued": count}

    return top_up


def _make_fill(role, platform_cfg, picker, writer, latency_guard):
    from hatchet_sdk import NonRetryableException

    def fill(input, _ctx):
        if input.get("llm_role") != role:
            raise ValueError(f"task requires llm_role {role}")
        try:
            return run_fill(
                picker.next(),
                role=role,
                platform_cfg=platform_cfg,
                chat=run_chat,
                latency_guard=latency_guard,
                writer=writer,
                when=datetime.now(timezone.utc),
            )
        except LatencyGuardError:
            # A refused run is skipped; the next cron tick tops up instead of retrying here.
            logger.info("fill run skipped by latency guard role=%s", role)
            return {"status": "skipped", "reason": "latency_guard", "written": 0}
        except Exception as exc:
            raise NonRetryableException(f"fill run failed: {type(exc).__name__}") from exc

    return fill


def build_fill_tasks(hatchet, worker_config):
    """Return the fill and top-up tasks for each mapped role, or [] when fill is not configured."""
    fill = worker_config.get("fill")
    if fill is None:
        return []
    from hatchet_sdk import (
        ConcurrencyExpression,
        ConcurrencyLimitStrategy,
        Priority,
    )

    picker = ChunkPicker(load_chunks(fill["corpus_dir"]))
    writer = JsonlWriter(fill["output_dir"])
    latency_guard = worker_config.get("latency_guard")
    tasks = []
    for role, platform_name in fill["roles"].items():
        platform_cfg = worker_config["platforms"][platform_name]
        max_runs = worker_config["roles"][role]["max_runs"]
        # Same tenant-scoped name as the agent task for this role, so both share one cap.
        run_concurrency = ConcurrencyExpression(
            expression="input.llm_role",
            max_runs=max_runs,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
            name=f"gpu-{role.removeprefix('gpu-')}",
            is_tenant_scoped=True,
        )
        # run_chat may spend timeout_s on the latency-guard query and timeout_s on the completion.
        execution_timeout = timedelta(seconds=2 * platform_cfg["timeout_s"] + 60)
        active_window = SCHEDULE_TIMEOUT + execution_timeout + ACTIVE_MARGIN
        if active_window >= timedelta(days=7):
            raise ValueError("fill platform timeout_s is too long to count active runs")
        fill_task = hatchet.task(
            name=f"gpu-qa-fill-{role}",
            input_validator=dict,
            concurrency=[run_concurrency],
            retries=0,
            schedule_timeout=SCHEDULE_TIMEOUT,
            execution_timeout=execution_timeout,
            default_priority=Priority.LOW,
        )(_make_fill(role, platform_cfg, picker, writer, latency_guard))
        # One top-up at a time per role, so two cron ticks never both count the same deficit.
        topup_concurrency = ConcurrencyExpression(
            expression=f"'{role}'",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
            name=f"gpu-qa-topup-{role}",
            is_tenant_scoped=True,
        )
        topup_task = hatchet.task(
            name=f"gpu-qa-topup-{role}",
            on_crons=[fill["cron"]],
            concurrency=[topup_concurrency],
            execution_timeout=timedelta(minutes=5),
            default_priority=Priority.LOW,
        )(_make_top_up(hatchet, fill_task, role, max_runs, active_window))
        tasks.extend([fill_task, topup_task])
    return tasks
