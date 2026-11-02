"""Build the low-priority scheduled evaluation tasks."""

import os
from datetime import timedelta
from pathlib import Path

from adapter import LatencyGuardError, _check_latency_guard
from evals.parse_experiment import run_parse_experiment
from evals.sync_judges import sync


def _cron_list(value):
    return [value] if value else []


def build_tasks(hatchet, evals_config, latency_guard=None):
    from hatchet_sdk import (
        ConcurrencyExpression,
        ConcurrencyLimitStrategy,
        Context,
        NonRetryableException,
        Priority,
    )

    prompts_dir = Path(evals_config["prompts_dir"])

    def sync_judges(_input, _ctx: Context):
        try:
            return sync(prompts_dir / "agents/judges")
        except Exception:
            raise NonRetryableException("judge sync failed") from None

    tasks = [
        hatchet.task(
            name="eval-sync-judges",
            on_crons=_cron_list(evals_config["judges_sync_cron"]),
            default_priority=Priority.LOW,
            execution_timeout=timedelta(minutes=5),
        )(sync_judges)
    ]

    def make_parse_handler(role, dataset):
        def parse_experiment(_input, _ctx: Context):
            try:
                if latency_guard is not None:
                    _check_latency_guard(latency_guard, 120)
                result = run_parse_experiment(
                    experiment_name=f"{dataset}-{role}",
                    dataset_name=dataset,
                    role=role,
                    prompts_dir=prompts_dir,
                    base_url=os.environ["LITELLM_BASE_URL"],
                    api_key=os.environ["LITELLM_API_KEY"],
                )
                return result.format()
            except LatencyGuardError:
                raise
            except Exception:
                raise NonRetryableException("parse experiment failed") from None

        return parse_experiment

    for role_config in evals_config["roles"]:
        role = role_config["role"]
        dataset = role_config["dataset"]
        concurrency = ConcurrencyExpression(
            expression=f"'{role}'",
            max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
            name=f"eval-parse-{role}",
            is_tenant_scoped=True,
        )
        tasks.append(
            hatchet.task(
                name=f"eval-parse-{role}",
                concurrency=[concurrency],
                on_crons=_cron_list(evals_config["cron"]),
                retries=6,
                backoff_factor=2.0,
                backoff_max_seconds=300,
                execution_timeout=timedelta(hours=1),
                default_priority=Priority.LOW,
            )(make_parse_handler(role, dataset))
        )
    return tasks
