"""Check schedule_export.py reconciles a schedule that exists but is disabled.

The branch under test is the one that used to be absent. `get_or_create` only
applies its `defaults` when it creates, so a ScheduledJob disabled in the UI
survived every converge while the script reported SCHEDULE_EXISTS — present,
reconciled, and not running. Nothing published, and nothing said so.

As with the ordering guard, the branches that carry the evidence are the ones
where the script must NOT report plain success: the disabled schedule must be
re-enabled, and an unregistered job must print SCHEDULE_SKIPPED so the
converge-side assert can fail on it.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import types
from pathlib import Path
from typing import Any, Optional

SCRIPT = Path(__file__).resolve().parents[1] / "roles/nautobot/files/schedule_export.py"


class Obj:
    """Minimal stand-in for a Django model instance."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)
        self.saved = False

    def save(self) -> None:
        """Record that the script persisted its change."""
        self.saved = True


class Manager:
    """Stand-in for a Django manager, canned per scenario."""

    def __init__(self, first: Optional[Obj] = None, existing: Optional[Obj] = None) -> None:
        self._first = first
        self._existing = existing

    def filter(self, **_kwargs: Any) -> "Manager":
        """Filtering does not change a canned result."""
        return self

    def order_by(self, *_args: Any) -> "Manager":
        """Ordering does not change a canned result."""
        return self

    def first(self) -> Optional[Obj]:
        """Return the canned object, or None for an empty result."""
        return self._first

    def get_or_create(self, **kwargs: Any) -> tuple[Obj, bool]:
        """Return the canned existing object, or create from `defaults`."""
        if self._existing is not None:
            return self._existing, False
        return Obj(**kwargs.get("defaults", {})), True


def run(job: Optional[Obj], existing: Optional[Obj], superuser: bool = True) -> str:
    """Execute the script against stubbed Django/Nautobot and return its stdout."""
    extras_models = types.ModuleType("nautobot.extras.models")
    extras_models.Job = types.SimpleNamespace(objects=Manager(first=job))
    extras_models.ScheduledJob = types.SimpleNamespace(objects=Manager(existing=existing))

    extras_choices = types.ModuleType("nautobot.extras.choices")
    extras_choices.JobExecutionType = types.SimpleNamespace(TYPE_CUSTOM="custom")

    auth = types.ModuleType("django.contrib.auth")
    auth.get_user_model = lambda: types.SimpleNamespace(
        objects=Manager(first=Obj(pk=1) if superuser else None)
    )

    utils = types.ModuleType("django.utils")
    utils.timezone = types.SimpleNamespace(now=lambda: "2026-08-09T00:00:00Z")

    stubs = {
        "django": types.ModuleType("django"),
        "django.contrib": types.ModuleType("django.contrib"),
        "django.contrib.auth": auth,
        "django.utils": utils,
        "nautobot": types.ModuleType("nautobot"),
        "nautobot.extras": types.ModuleType("nautobot.extras"),
        "nautobot.extras.models": extras_models,
        "nautobot.extras.choices": extras_choices,
    }
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("schedule_export", SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            spec.loader.exec_module(module)
        return buffer.getvalue()
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


def main() -> None:
    """Exercise every branch, asserting the non-success ones hardest."""
    job = Obj(name="Export Nautobot Inventory to S3", enabled=True, class_path="x.Y")

    # The regression: present but disabled must be re-enabled AND persisted.
    disabled = Obj(enabled=False)
    out = run(job=job, existing=disabled)
    assert "SCHEDULE_REENABLED" in out, out
    assert disabled.enabled is True, "a disabled schedule was left disabled"
    assert disabled.saved is True, "the re-enable was never persisted"

    # An already-enabled schedule is left alone and reports no change.
    enabled = Obj(enabled=True)
    out = run(job=job, existing=enabled)
    assert "SCHEDULE_EXISTS" in out, out
    assert enabled.saved is False, "an enabled schedule was written unnecessarily"

    # First run on a fresh instance creates it.
    out = run(job=job, existing=None)
    assert "SCHEDULE_CREATED" in out, out

    # The failure branches must be reported as skips, because the converge-side
    # assert in tasks/main.yml fails on exactly this marker. If these ever
    # printed a success marker instead, the converge would go green with no
    # schedule and the export would stop silently — the original defect.
    out = run(job=None, existing=None)
    assert "SCHEDULE_SKIPPED job-not-registered" in out, out

    out = run(job=job, existing=None, superuser=False)
    assert "SCHEDULE_SKIPPED no-superuser" in out, out

    print("schedule_export: all branches OK")


if __name__ == "__main__":
    main()
