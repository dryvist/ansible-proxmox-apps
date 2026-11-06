"""Register the disabled-by-default daily engine comparison."""

from datetime import timedelta

from engineab.digest import run


def build_tasks(hatchet, config, latency_guard=None):
    from hatchet_sdk import Context, NonRetryableException, Priority
    from adapter import _check_latency_guard

    def digest(_input, _ctx: Context):
        try:
            if latency_guard is not None:
                _check_latency_guard(latency_guard, 30)
            return run(config)
        except Exception:
            raise NonRetryableException("engine comparison failed") from None

    return [hatchet.task(name="engineab-pr-digest", on_crons=["29 7 * * *"],
                         retries=0, execution_timeout=timedelta(minutes=30),
                         default_priority=Priority.LOW)(digest)]
