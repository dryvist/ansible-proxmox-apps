"""Contract check for the seed-job runner's enqueue call.

The failure this exists for reached production: Nautobot 3.2 takes a job's
variables as ONE ``job_kwargs`` mapping and rejects a call that omits it, so
every PLAIN job (no variables) stopped running with "`job_kwargs` has to be
defined" — while the SSoT jobs, which pass ``dryrun``, kept working through the
deprecated splat. Five jobs green and two silently dead is exactly the
partial-success shape the converge is supposed to make impossible.

Stubs django/nautobot the same way the other job tests do, then drives
``enqueue`` against both signatures.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "roles/nautobot/files/run_seed_jobs.py"


class Recorder:
    """Captures how enqueue_job was called."""

    def __init__(self, *, modern: bool) -> None:
        self.modern = modern
        self.calls: list[dict] = []

    def enqueue_job(self, job, user, job_kwargs=None, **splat):
        """Stand in for JobResult.enqueue_job under either signature."""
        if self.modern:
            # Nautobot 3.2: the mapping is required and the splat is gone.
            if splat:
                raise TypeError("unexpected keyword arguments: %s" % sorted(splat))
            if job_kwargs is None:
                raise ValueError("`job_kwargs` has to be defined.")
            self.calls.append({"form": "modern", "kwargs": job_kwargs})
        else:
            # Pre-3.2: no job_kwargs parameter at all.
            if job_kwargs is not None:
                raise TypeError("enqueue_job() got an unexpected keyword 'job_kwargs'")
            self.calls.append({"form": "legacy", "kwargs": splat})
        return types.SimpleNamespace(status="SUCCESS", refresh_from_db=lambda: None)


def load(recorder, *, registered: bool = False):
    """Import run_seed_jobs.py with django/nautobot stubbed out.

    ``registered=True`` makes every job resolve to an enabled Job, so the
    module body actually runs the seed loop — that is the only way to observe
    the process exit code, exposed as ``module.TEST_EXIT_CODE``.
    """
    auth = types.ModuleType("django.contrib.auth")
    auth.get_user_model = lambda: types.SimpleNamespace(
        objects=types.SimpleNamespace(
            filter=lambda **kw: types.SimpleNamespace(
                order_by=lambda *a: types.SimpleNamespace(first=lambda: "superuser")
            )
        )
    )
    # No Job is registered, so the module body's own pass reports every job
    # JOB_SKIPPED and exits 1 — caught below. This test drives `enqueue`
    # directly; the module-level run is only incidental to importing it.
    extras = types.ModuleType("nautobot.extras.models")
    job = types.SimpleNamespace(enabled=True, save=lambda: None) if registered else None
    extras.Job = type(
        "Job",
        (),
        {"objects": types.SimpleNamespace(
            filter=lambda **kw: types.SimpleNamespace(first=lambda: job)
        )},
    )
    extras.JobResult = recorder

    for name, mod in {
        "django": types.ModuleType("django"),
        "django.contrib": types.ModuleType("django.contrib"),
        "django.contrib.auth": auth,
        "nautobot": types.ModuleType("nautobot"),
        "nautobot.extras": types.ModuleType("nautobot.extras"),
        "nautobot.extras.models": extras,
    }.items():
        sys.modules[name] = mod

    sys.modules.pop("run_seed_jobs", None)
    spec = importlib.util.spec_from_file_location("run_seed_jobs", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_seed_jobs"] = module
    # The module body ends in `sys.exit(1)` when a job fails; it never reaches
    # that here because SEED_JOBS resolution is what we are bypassing. Guard
    # anyway so an import cannot kill the test process.
    exit_code = 0
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        exit_code = exc.code or 0
    module.TEST_EXIT_CODE = exit_code
    return module


def main() -> None:
    """Both signatures must work, and a plain job must never send nothing."""
    # Validate the instrument first: the modern stub must actually reproduce
    # the production failure. If it accepts the old call shape, every
    # assertion below passes for free and proves nothing.
    rec = Recorder(modern=True)
    try:
        rec.enqueue_job("job", "user")
    except ValueError as exc:
        assert "job_kwargs" in str(exc), exc
    else:  # pragma: no cover - the stub would be useless
        raise AssertionError("modern stub accepted a call with no job_kwargs")
    try:
        rec.enqueue_job("job", "user", dryrun=False)
    except TypeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("modern stub accepted the removed splat form")

    # Nautobot 3.2: the mapping is passed, present-but-empty for a plain job.
    rec = Recorder(modern=True)
    mod = load(rec)
    mod.enqueue("job", {})
    mod.enqueue("job", {"dryrun": False})
    assert [c["form"] for c in rec.calls] == ["modern", "modern"], rec.calls
    assert rec.calls[0]["kwargs"] == {}, "a plain job must send an EMPTY mapping, not none"
    assert rec.calls[1]["kwargs"] == {"dryrun": False}

    # Pre-3.2: falls back to the splat rather than failing.
    rec = Recorder(modern=False)
    mod = load(rec)
    mod.enqueue("job", {"dryrun": False})
    assert rec.calls == [{"form": "legacy", "kwargs": {"dryrun": False}}], rec.calls

    # The registry must not drift: every job the runner enqueues has to be one
    # of the two kinds, or it silently gets the wrong kwargs.
    rec = Recorder(modern=True)
    mod = load(rec)
    # Every job the runner enqueues must be classified, so it gets the right
    # kwargs. Not the reverse: a slice-backed job is dropped from SEED_JOBS
    # when its slice is empty, while staying classified in SSOT_JOBS.
    assert set(mod.SSOT_JOBS) | set(mod.PLAIN_JOBS) >= set(mod.SEED_JOBS)
    assert not (set(mod.SSOT_JOBS) & set(mod.PLAIN_JOBS)), "a job cannot be both kinds"
    assert "Seed Hardware Inventory" in mod.PLAIN_JOBS

    print("nautobot_run_seed_jobs: OK")


if __name__ == "__main__":
    main()
