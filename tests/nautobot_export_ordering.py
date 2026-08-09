"""Check the export ordering guard: no ingest since the last export means refuse.

Asserts that the guard REFUSES, not merely that it passes. A guard never
observed to fail is indistinguishable from no guard, and an export that always
succeeds is exactly the condition this code exists to rule out — so the
refusing branches are the ones that carry the evidence.

The fake manager also rejects a JobResult lookup by name, because that field
holds more than one form per job and a filter on it would match only some of a
job's results. See INGEST_JOB_MODULES in the job module.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from nautobot_export_shape import load_export_module

JOBS_DIR = Path(__file__).resolve().parents[1] / "roles/nautobot/files/jobs"
EARLIER = datetime(2026, 7, 18, 21, 54, tzinfo=timezone.utc)
LATER = EARLIER + timedelta(days=20)


class FakeQuerySet:
    """Stand-in for the chained ORM calls the guard makes."""

    def __init__(self, value: Optional[datetime]) -> None:
        self._value = value

    def order_by(self, *_args: Any) -> "FakeQuerySet":
        """Ordering does not change a single canned value."""
        return self

    def values_list(self, *_args: Any, **_kwargs: Any) -> "FakeQuerySet":
        """Field selection does not change a single canned value."""
        return self

    def first(self) -> Optional[datetime]:
        """Return the canned value, or None for an empty result."""
        return self._value


class FakeJobResultManager:
    """Routes a filter() to the right canned timestamp by what it filters on.

    Deliberately strict about the lookup keys. JobResult.name is NOT a stable
    identifier — the live instance holds both "Export Nautobot Inventory to S3"
    and "export_nautobot.ExportNautobotToS3" for the same job, and scheduled
    runs write the latter. A guard filtering on name would miss every scheduled
    run and pass forever. So this fake raises on a name lookup rather than
    answering it, which turns that regression into a test failure instead of a
    guard that quietly stops working.
    """

    def __init__(self, last_export: Optional[datetime], last_ingest: Optional[datetime]) -> None:
        self.last_export = last_export
        self.last_ingest = last_ingest
        self.lookups: list[str] = []

    def filter(self, **kwargs: Any) -> FakeQuerySet:
        """Return the export or ingest timestamp depending on the lookup used."""
        self.lookups.extend(kwargs)
        for key in kwargs:
            if key.startswith("name"):
                raise AssertionError(
                    f"guard filtered JobResult on {key!r}; that field is not stable — "
                    "match on job_model instead"
                )
        if "job_model__module_name__in" in kwargs:
            return FakeQuerySet(self.last_ingest)
        if "job_model__module_name" in kwargs:
            return FakeQuerySet(self.last_export)
        raise AssertionError(f"unexpected JobResult lookup: {sorted(kwargs)}")


class Recorder:
    """Collects logger calls so a passing run can be told from a refusing one."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str, *args: Any) -> None:
        """Record a formatted info line."""
        self.messages.append(message % args if args else message)


def run_guard(module: Any, last_export: Optional[datetime], last_ingest: Optional[datetime]):
    """Invoke the guard against canned job history; return the recorder or the error."""
    job = module.ExportNautobotToS3.__new__(module.ExportNautobotToS3)
    job.logger = Recorder()
    module.JobResult.objects = FakeJobResultManager(last_export, last_ingest)
    try:
        job._assert_ingest_ordering()  # noqa: SLF001 - the unit under test
    except RuntimeError as err:
        return ("refused", str(err))
    return ("passed", job.logger.messages)


def main() -> None:
    """Exercise every branch of the ordering guard."""
    module = load_export_module()

    # The real defect: an export already happened, and no ingest has run since.
    outcome, detail = run_guard(module, last_export=LATER, last_ingest=EARLIER)
    assert outcome == "refused", f"stale ingest must refuse, got {outcome}: {detail}"
    assert "Refusing to publish" in detail, detail
    # The message has to say what to do, or an operator reaches for the schedule.
    assert "Re-run an ingest job first" in detail, detail

    # Ingest has never run at all — same refusal, and it must not crash on None.
    outcome, detail = run_guard(module, last_export=LATER, last_ingest=None)
    assert outcome == "refused", f"absent ingest must refuse, got {outcome}"
    assert "never" in detail, detail

    # Normal event-driven flow: an ingest completed after the last export.
    outcome, detail = run_guard(module, last_export=EARLIER, last_ingest=LATER)
    assert outcome == "passed", f"ingest after export must pass, got {detail}"

    # First run on a fresh instance: nothing to be newer than, so allow it.
    # Without this branch the guard would deadlock a new deployment.
    outcome, detail = run_guard(module, last_export=None, last_ingest=None)
    assert outcome == "passed", f"first-ever export must pass, got {detail}"
    assert any("No prior successful export" in m for m in detail), detail

    # Every named module must be a job file that actually ships. A typo here
    # silently shrinks what counts as an ingest; typo them all and no ingest is
    # ever seen, so the guard refuses forever and someone reverts it.
    #
    # Checked against the deployed directory rather than against a copy of the
    # same tuple — restating the list would assert only that I typed it twice.
    shipped = {path.stem for path in JOBS_DIR.glob("*.py")}
    missing = set(module.INGEST_JOB_MODULES) - shipped
    assert not missing, f"INGEST_JOB_MODULES names non-existent job modules: {sorted(missing)}"
    assert module.EXPORT_JOB_MODULE in shipped, module.EXPORT_JOB_MODULE

    # Every ssot_* job file should be in the ingest list. A new seed job added
    # without registering it here would not count as an ingest, so the export
    # could publish ahead of it.
    unregistered = {n for n in shipped if n.startswith("ssot_")} - set(
        module.INGEST_JOB_MODULES
    ) - {"ssot_common"}
    assert not unregistered, f"seed job(s) missing from INGEST_JOB_MODULES: {sorted(unregistered)}"

    print("nautobot export ordering guard: 4 cases OK (2 refuse, 2 pass) + modules match shipped files")


if __name__ == "__main__":
    sys.exit(main())
