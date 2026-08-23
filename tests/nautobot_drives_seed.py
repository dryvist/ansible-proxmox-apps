"""The drive sync refuses to run on an empty source, and never fakes a serial.

This job is the only one in the seed set that DELETES. Every other seed is
additive, so an absent slice harmlessly contributes nothing — here the same
absent slice would remove every drive record in the database. Two independent
guards exist for that, and this pins both:

* the runner ENROLS the job only when the bundle actually carries drives, so an
  estate that has not gathered them yet converges quietly;
* the job itself RAISES on an empty slice, so a hand-run from the Nautobot UI
  fails loudly instead of emptying the inventory.

It also pins the serial rule. For SAS drives the source reports the WWN in the
`serial` field, and writing that through would put a fabricated identity on a
device forever, indistinguishable from a real one.

The django/nautobot stubs come from nautobot_run_seed_jobs rather than being
restated here — one stub set, one place to fix when Nautobot moves.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path

from nautobot_run_seed_jobs import Recorder
from nautobot_run_seed_jobs import load as load_runner

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "roles/nautobot/files/jobs"

DRIVE_JOB = "Sync Drive Inventory from Proxmox"


def install_job_stubs() -> None:
    """Install the smallest fake modules that let ssot_drives import.

    Nothing is instantiated by these tests — both guards fire before any object
    is built — so a bare type is enough for each.
    """
    diffsync = types.ModuleType("diffsync")
    diffsync.Adapter = type("Adapter", (), {"__init__": lambda self, *a, **k: None})

    jobs_mod = types.ModuleType("nautobot.apps.jobs")
    jobs_mod.register_jobs = lambda *a, **k: None

    dcim = types.ModuleType("nautobot.dcim.models")
    dcim.Device = type("Device", (), {})
    dcim.InventoryItem = type("InventoryItem", (), {})

    contrib = types.ModuleType("nautobot_ssot.contrib")
    contrib.NautobotModel = type("NautobotModel", (), {})
    contrib.NautobotAdapter = type("NautobotAdapter", (), {})

    base = types.ModuleType("nautobot_ssot.jobs.base")
    base.DataSource = type("DataSource", (), {"logger": None})

    common = types.ModuleType("ssot_common")
    common.ensure_manufacturer = lambda *a, **k: None
    common.load_seed = lambda: {"drives": []}

    for name, mod in {
        "diffsync": diffsync,
        "nautobot.apps": types.ModuleType("nautobot.apps"),
        "nautobot.apps.jobs": jobs_mod,
        "nautobot.dcim": types.ModuleType("nautobot.dcim"),
        "nautobot.dcim.models": dcim,
        "nautobot_ssot": types.ModuleType("nautobot_ssot"),
        "nautobot_ssot.contrib": contrib,
        "nautobot_ssot.jobs": types.ModuleType("nautobot_ssot.jobs"),
        "nautobot_ssot.jobs.base": base,
        "ssot_common": common,
    }.items():
        sys.modules[name] = mod


def load_job():
    """Import ssot_drives.py against the stubs."""
    spec = importlib.util.spec_from_file_location("ssot_drives", JOBS / "ssot_drives.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ssot_drives"] = module
    spec.loader.exec_module(module)
    return module


def check_refuses_empty_source(drives_mod, drives) -> None:
    """The job must raise rather than sync an empty source."""
    sys.modules["ssot_common"].load_seed = lambda: {"drives": drives}
    job = drives_mod.SyncDrivesFromSeed()
    try:
        job.load_source_adapter()
    except ValueError as exc:
        assert "delete" in str(exc).lower(), (
            "the refusal must say WHY an empty source is dangerous, or the next "
            f"reader removes the guard as pointless: {exc}"
        )
        return
    raise AssertionError(
        f"load_source_adapter() accepted {drives!r} — an empty source against a "
        "delete-capable target removes every drive in Nautobot."
    )


def check_serial_rule(drives_mod) -> None:
    """A serial that merely repeats the WWN is not a serial."""
    same = drives_mod._same_identifier

    assert same("0x5000cca25dc1b2a3", "5000cca25dc1b2a3"), "0x prefix must normalise"
    assert same("5000CCA25DC1B2A3", "5000cca25dc1b2a3"), "comparison must be case-insensitive"

    # The must-NOT-mangle control. An earlier revision also stripped a leading
    # "3" (the SCSI-name prefix in scsi-3<wwn>), which corrupts any real serial
    # beginning with 3 — the estate carries one. Without this case, that bug
    # passes every other assertion here.
    assert not same("3ABC123", "ABC123"), (
        "a leading 3 is being stripped — that silently mangles real serials "
        "that happen to start with 3"
    )

    assert not same("", "5000cca25dc1b2a3"), "an absent serial is not a WWN match"
    assert not same("EXAMPLESERIAL1", ""), "an absent WWN cannot prove anything"
    assert not same("EXAMPLESERIAL1", "5000cca25dc1b2a3"), "distinct values must not match"


def check_runner_gate() -> None:
    """The runner enrols the drive job only when the bundle carries drives."""
    original = os.environ.get("NAUTOBOT_SEED_FILE")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "seed.json"
        os.environ["NAUTOBOT_SEED_FILE"] = str(path)
        try:
            cases = [
                (None, False, "a missing bundle"),
                ({"nodes": [{"name": "n"}]}, False, "a bundle with no drives key"),
                ({"drives": []}, False, "an EMPTY drives slice"),
                ({"drives": [{"node": "n", "serial": "EXAMPLESERIAL1"}]}, True, "a populated slice"),
            ]
            for payload, expected, label in cases:
                if payload is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(json.dumps(payload))
                module = load_runner(Recorder(modern=True))
                enrolled = DRIVE_JOB in module.SEED_JOBS
                assert enrolled is expected, (
                    f"{label}: expected enrolled={expected}, got {enrolled}. "
                    "Enrolling on an empty slice deletes the drive inventory; "
                    "skipping on a populated one silently stops syncing."
                )
                # The job must also carry dryrun=False, or it computes a diff
                # and commits nothing while reporting SUCCESS.
                if expected:
                    assert DRIVE_JOB in module.SSOT_JOBS, (
                        "the drive job is enrolled but not in SSOT_JOBS, so it "
                        "runs as a dry run and persists nothing while passing"
                    )
        finally:
            if original is None:
                os.environ.pop("NAUTOBOT_SEED_FILE", None)
            else:
                os.environ["NAUTOBOT_SEED_FILE"] = original


if __name__ == "__main__":
    check_runner_gate()

    install_job_stubs()
    job_mod = load_job()
    check_refuses_empty_source(job_mod, [])
    check_refuses_empty_source(job_mod, None)
    check_serial_rule(job_mod)

    print("nautobot drive sync: OK (4 gate cases, 2 empty-source refusals, 6 serial cases)")
