"""VM sizing reaches Nautobot, and an absent value never becomes a zero.

Nautobot models `vcpus`/`memory`/`disk` natively, so the golden rule binds: they
must be synced attributes, not left for a human to fill in. They read null for
every guest today because they were simply missing from `_attributes`.

The subtle half is the difference between "not published" and "published as
zero". Nautobot renders 0 as a real value, so a guest would display as having no
CPU or no disk — worse than blank, because blank is visibly unknown while 0
looks authoritative. `_positive_int` is the guard, and this pins it.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "roles/nautobot/files/jobs"


def install_stubs() -> None:
    """Smallest fakes that let ssot_virtualization import."""
    diffsync = types.ModuleType("diffsync")
    diffsync.Adapter = type("Adapter", (), {"__init__": lambda self, *a, **k: None})

    jobs_mod = types.ModuleType("nautobot.apps.jobs")
    jobs_mod.register_jobs = lambda *a, **k: None

    virt = types.ModuleType("nautobot.virtualization.models")
    virt.VirtualMachine = type("VirtualMachine", (), {})

    contrib = types.ModuleType("nautobot_ssot.contrib")
    contrib.NautobotAdapter = type("NautobotAdapter", (), {})

    base = types.ModuleType("nautobot_ssot.jobs.base")
    base.DataSource = type("DataSource", (), {"logger": None})

    common = types.ModuleType("ssot_common")
    common.STATUS_ACTIVE = "Active"
    common.AdditiveNautobotModel = type("AdditiveNautobotModel", (), {})
    common.ensure_location = lambda *a, **k: None
    common.ensure_role = lambda *a, **k: None
    common.ensure_tag = lambda *a, **k: None
    common.load_seed = lambda: {"virtual_machines": []}

    for name, mod in {
        "diffsync": diffsync,
        "nautobot": types.ModuleType("nautobot"),
        "nautobot.apps": types.ModuleType("nautobot.apps"),
        "nautobot.apps.jobs": jobs_mod,
        "nautobot.virtualization": types.ModuleType("nautobot.virtualization"),
        "nautobot.virtualization.models": virt,
        "nautobot_ssot": types.ModuleType("nautobot_ssot"),
        "nautobot_ssot.contrib": contrib,
        "nautobot_ssot.jobs": types.ModuleType("nautobot_ssot.jobs"),
        "nautobot_ssot.jobs.base": base,
        "ssot_common": common,
    }.items():
        sys.modules[name] = mod


def load_job():
    """Import ssot_virtualization.py against the stubs."""
    spec = importlib.util.spec_from_file_location(
        "ssot_virtualization", JOBS / "ssot_virtualization.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["ssot_virtualization"] = module
    spec.loader.exec_module(module)
    return module


def check_sizing_is_synced(mod) -> None:
    """The three fields must be synced attributes, or they stay null forever."""
    attrs = mod.VirtualMachineModel._attributes
    for field in ("vcpus", "memory", "disk"):
        assert field in attrs, (
            f"{field} is not in _attributes, so DiffSync never writes it and "
            "Nautobot keeps reading null for every guest"
        )
    # The pre-existing attributes must survive — without this, replacing the
    # tuple wholesale would pass.
    for field in ("cluster__name", "status__name", "role__name"):
        assert field in attrs, f"{field} was dropped from _attributes"


def check_absent_never_becomes_zero(mod) -> None:
    """An unpublished value is None, never 0."""
    positive = mod._positive_int

    # Absent / unusable -> None, so Nautobot leaves the field blank.
    for absent in (None, "", "  ", "abc", [], {}):
        assert positive(absent) is None, f"{absent!r} should be None, got {positive(absent)!r}"

    # Zero and negatives are NOT sizing. This is the whole point: 0 renders as a
    # real value and reads as "this guest has no CPU".
    for zero in (0, -1, "0", "-4"):
        assert positive(zero) is None, f"{zero!r} must not be recorded as sizing"

    # Real values survive, including string forms from JSON.
    assert positive(4) == 4
    assert positive("8192") == 8192
    assert positive(24) == 24


if __name__ == "__main__":
    install_stubs()
    job = load_job()
    check_sizing_is_synced(job)
    check_absent_never_becomes_zero(job)
    print("nautobot vm sizing: OK (6 attribute cases, 10 zero/absent cases, 3 passthrough)")
