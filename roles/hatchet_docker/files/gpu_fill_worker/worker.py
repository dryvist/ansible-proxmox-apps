"""Hatchet task definitions for one-shot GPU-fill agent dispatches."""

import os
from datetime import timedelta

from hatchet_sdk import (
    ConcurrencyExpression,
    ConcurrencyLimitStrategy,
    Context,
    Hatchet,
    NonRetryableException,
    Priority,
)
from pydantic import BaseModel

from adapter import LatencyGuardError, run_agent
from config import load_config


class AgentRunInput(BaseModel):
    agent: str
    platform: str
    llm_role: str
    privacy_class: str
    payload: dict


def _make_handler(configured_role, worker_config):
    def run(input: AgentRunInput, ctx: Context) -> dict:
        if input.llm_role != configured_role:
            raise ValueError(f"task requires llm_role {configured_role}")
        platform = worker_config["platforms"][input.platform]
        payload = input.model_dump(exclude={"platform"})
        try:
            return run_agent(platform, payload, latency_guard=worker_config.get("latency_guard"))
        except LatencyGuardError:
            raise  # Hatchet retries a latency hold with backoff.
        except Exception as exc:
            # Never re-run a dispatched agent; only a latency hold retries.
            raise NonRetryableException(str(exc)) from exc

    return run


def build_tasks(hatchet, worker_config):
    execution_timeout = timedelta(
        seconds=max(platform["timeout_s"] for platform in worker_config["platforms"].values())
    )
    tasks = []
    for llm_role, role_config in worker_config["roles"].items():
        concurrency_name = f"gpu-{llm_role.removeprefix('gpu-')}"
        concurrency = ConcurrencyExpression(
            expression="input.llm_role",
            max_runs=role_config["max_runs"],
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
            name=concurrency_name,
            is_tenant_scoped=True,
        )
        task = hatchet.task(
            name=f"gpu-fill-{llm_role}",
            input_validator=AgentRunInput,
            concurrency=[concurrency],
            retries=6,
            backoff_factor=2.0,
            backoff_max_seconds=300,
            execution_timeout=execution_timeout,
            default_priority=Priority.LOW,
        )(_make_handler(llm_role, worker_config))
        tasks.append(task)
    return tasks


def main():
    worker_config = load_config(
        os.environ.get("GPU_FILL_WORKER_CONFIG", "/tmp/gpu-fill-worker.json")
    )
    hatchet = Hatchet()
    workflows = build_tasks(hatchet, worker_config)
    if "evals" in worker_config:
        from evals import build_tasks as build_eval_tasks

        workflows.extend(
            build_eval_tasks(hatchet, worker_config["evals"], worker_config.get("latency_guard"))
        )
    slots = sum(role["max_runs"] for role in worker_config["roles"].values())
    # One slot per eval task (judge sync plus one per role) so evals never take GPU-fill slots.
    slots += len(worker_config["evals"]["roles"]) + 1 if "evals" in worker_config else 0
    worker = hatchet.worker(
        "gpu-fill-worker",
        workflows=workflows,
        slots=slots,
    )
    worker.start()


if __name__ == "__main__":
    main()
