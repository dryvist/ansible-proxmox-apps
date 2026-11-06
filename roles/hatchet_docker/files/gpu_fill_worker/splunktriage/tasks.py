"""Register the opt-in private Splunk triage schedule."""

from datetime import timedelta

from adapter import _check_latency_guard
from splunktriage import CRON, run


def build_tasks(hatchet, config, latency_guard=None):
    from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy, Priority

    def triage(_input, _ctx):
        try:
            if latency_guard is not None:
                _check_latency_guard(latency_guard, 120)
            return run(config)
        except Exception:
            # Hatchet logs must never contain alert data, URLs, or credentials.
            raise RuntimeError("Splunk triage failed; checkpoint retained") from None

    return [hatchet.task(
        name="gpu-splunk-triage", on_crons=[CRON], retries=0,
        concurrency=[ConcurrencyExpression(
            expression="'splunktriage'", max_runs=1,
            limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
            name="gpu-splunk-triage", is_tenant_scoped=True,
        )], execution_timeout=timedelta(minutes=9), default_priority=Priority.LOW,
    )(triage)]
