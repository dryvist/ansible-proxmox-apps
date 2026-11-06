"""Register the scheduled low-priority release digest task."""

from datetime import timedelta

from adapter import LatencyGuardError
from release_digest.digest import DigestPostError, run_digest


def build_tasks(hatchet, config, platforms, latency_guard=None):
    from hatchet_sdk import NonRetryableException, Priority

    platform = platforms[config["chat_platform"]]

    def release_digest(_input, _ctx):
        try:
            return run_digest(config, platform, latency_guard=latency_guard)
        except LatencyGuardError:
            raise
        except DigestPostError as exc:
            raise NonRetryableException(str(exc)) from None
        except ValueError as exc:
            raise NonRetryableException(str(exc)) from None

    task = hatchet.task(
        name="release-digest",
        on_crons=[config["cron"]],
        retries=6,
        backoff_factor=2.0,
        backoff_max_seconds=300,
        execution_timeout=timedelta(hours=1),
        default_priority=Priority.LOW,
    )(release_digest)
    return [task]
