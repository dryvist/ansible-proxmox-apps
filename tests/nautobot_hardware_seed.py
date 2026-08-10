"""Behaviour check for the hardware seed job (roles/nautobot/files/jobs).

Stubs django/nautobot the same way tests/nautobot_export_shape.py does, so the
job's real placement logic runs without a Nautobot install. What is actually
being pinned down here is the part that is easy to get quietly wrong:

* a spare must land at a Location with NO parent bay, and an installed part at
  a bay with NO location — the model forbids both at once;
* a component whose stated chassis does not exist must be filed as a spare with
  a warning, never hung off an invented placeholder Device;
* a chassis row the rack-server seed owns must be left alone, not re-created
  under a second name.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "roles/nautobot/files/jobs"


class Record:
    """An object with named attributes, standing in for a model instance."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class FakeManager:
    """Minimal Django manager: enough for get_or_create/update_or_create/filter."""

    def __init__(self, store: list[Record], key: str) -> None:
        self.store, self.key = store, key
        self.created: list[Record] = []

    def _match(self, **kwargs):
        wanted = {k: v for k, v in kwargs.items() if k != "defaults"}
        for item in self.store:
            if all(getattr(item, k, None) == v for k, v in wanted.items()):
                return item
        return None

    def filter(self, **kwargs):
        """Return a queryset-ish list supporting .first() and .exists()."""
        wanted = {k: v for k, v in kwargs.items()}
        found = [
            i for i in self.store if all(getattr(i, k, None) == v for k, v in wanted.items())
        ]
        return FakeQuerySet(found)

    def get_or_create(self, defaults=None, **kwargs):
        """Return (obj, created)."""
        existing = self._match(**kwargs)
        if existing is not None:
            return existing, False
        obj = Record(**{**(defaults or {}), **kwargs})
        self.store.append(obj)
        self.created.append(obj)
        return obj, True

    def update_or_create(self, defaults=None, **kwargs):
        """Return (obj, created), applying defaults on both paths."""
        existing = self._match(**kwargs)
        if existing is not None:
            existing.__dict__.update(defaults or {})
            return existing, False
        return self.get_or_create(defaults=defaults, **kwargs)


class FakeQuerySet(list):
    """List with the two queryset methods the job calls."""

    def first(self):
        """Return the first match or None."""
        return self[0] if self else None

    def exists(self) -> bool:
        """Return whether anything matched."""
        return bool(self)


class Collector:
    """Captures logger calls so a warning can be asserted on."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, msg, *args):  # noqa: D102
        self.warnings.append(msg % args if args else msg)

    def info(self, msg, *args):  # noqa: D102
        self.infos.append(msg % args if args else msg)


def install_stubs(seed_path: Path, devices: list[Record]) -> dict[str, Any]:
    """Install fake django/nautobot modules and return the object stores."""
    stores: dict[str, Any] = {
        "device": devices,
        "module": [],
        "module_bay": [],
        "module_type": [],
        "location": [Record(name="homelab")],
        "circuit": [],
    }

    def model(name, key):
        cls = type(name, (), {})
        cls.objects = FakeManager(stores[key], key)
        return cls

    device_cls = type("Device", (), {"objects": FakeManager(stores["device"], "device")})
    module_cls = type("Module", (), {"objects": FakeManager(stores["module"], "module")})
    bay_cls = type("ModuleBay", (), {"objects": FakeManager(stores["module_bay"], "module_bay")})
    stores["classes"] = {"Device": device_cls, "Module": module_cls, "ModuleBay": bay_cls}

    dcim = types.ModuleType("nautobot.dcim.models")
    dcim.Device, dcim.Module, dcim.ModuleBay = device_cls, module_cls, bay_cls
    for extra in ("DeviceType", "Location", "LocationType", "Manufacturer", "ModuleType", "Rack"):
        setattr(dcim, extra, model(extra, "module_type"))

    circuits_mod = types.ModuleType("nautobot.circuits.models")
    circuits_mod.Circuit = type(
        "Circuit", (), {"objects": FakeManager(stores["circuit"], "circuit")}
    )
    for extra in ("CircuitType", "Provider"):
        setattr(circuits_mod, extra, model(extra, "module_type"))

    jobs_mod = types.ModuleType("nautobot.apps.jobs")
    jobs_mod.Job = type("Job", (), {"logger": None})
    jobs_mod.BooleanVar = lambda **kw: None
    jobs_mod.register_jobs = lambda *a, **k: None

    for name, mod in {
        "nautobot": types.ModuleType("nautobot"),
        "nautobot.apps": types.ModuleType("nautobot.apps"),
        "nautobot.apps.jobs": jobs_mod,
        "nautobot.dcim": types.ModuleType("nautobot.dcim"),
        "nautobot.dcim.models": dcim,
        "nautobot.circuits": types.ModuleType("nautobot.circuits"),
        "nautobot.circuits.models": circuits_mod,
    }.items():
        sys.modules[name] = mod

    # ssot_common's scaffolding helpers are exercised against a live Nautobot,
    # not here; stub them so this test covers the placement logic only.
    common = types.ModuleType("ssot_common")
    common.STATUS_ACTIVE = "Active"
    common.ensure_location = lambda: Record(name="homelab")
    common.ensure_sublocation = lambda n: Record(name=n or "homelab")
    common.ensure_device_type = lambda m, mfr="": Record(model=m, manufacturer=mfr)
    common.ensure_module_type = lambda m, mfr="", pn="": Record(model=m, manufacturer=mfr)
    common.ensure_role = lambda n, *m: Record(name=n)
    common.ensure_status = lambda n, *m: Record(name=n)
    # Mirrors the real load_seed: every slice defaults to empty, so a document
    # missing a key behaves the same here as it does on the guest.
    common.load_seed = lambda: {
        "hardware_devices": [],
        "hardware_modules": [],
        "wan_circuits": [],
        **json.loads(seed_path.read_text(encoding="utf-8")),
    }
    sys.modules["ssot_common"] = common

    return stores


def load_job():
    """Import ssot_hardware.py with the stubs in place."""
    spec = importlib.util.spec_from_file_location("ssot_hardware", JOBS / "ssot_hardware.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(seed: dict, devices: list[Record], dryrun: bool = False):
    """Run the job against a seed document and return (job, stores)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(seed, handle)
        path = Path(handle.name)
    stores = install_stubs(path, devices)
    module = load_job()
    job = module.SeedHardware()
    job.logger = Collector()
    job.run(dryrun=dryrun)
    path.unlink()
    return job, stores


def row(hw_id, **over):
    """Build a seed row with sane defaults."""
    base = {
        "hw_id": hw_id,
        "quantity": 1,
        "category": "GPU",
        "manufacturer": "ASUS",
        "model": "Some Card",
        "part_number": "",
        "status": "Active",
        "status_note": "working",
        "location_note": "spares",
        "location": "spares",
        "purchased": "",
        "price": "",
        "section": "Compute",
        "installed_in": None,
    }
    base.update(over)
    return base


def main() -> None:
    """Run every assertion."""
    r540 = Record(name="r540")

    # A spare: location set, parent bay explicitly cleared.
    _, stores = run(
        {"hardware_devices": [], "hardware_modules": [row("GPU-SPARE")]}, [r540]
    )
    module = stores["module"][0]
    assert module.asset_tag == "GPU-SPARE"
    assert module.parent_module_bay is None, "a spare must not be in a bay"
    assert module.location is not None and module.location.name == "spares"

    # An installed part: bay set on the real device, location explicitly cleared.
    _, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [row("CPU-GOLD6230", installed_in="r540", location="r540")],
        },
        [r540],
    )
    module = stores["module"][0]
    assert module.location is None, "an installed module must not carry a location"
    assert module.parent_module_bay is not None
    assert module.parent_module_bay.parent_device is r540
    assert module.parent_module_bay.name == "CPU-GOLD6230"

    # A part naming a chassis that does not exist: filed as a spare, and said so.
    job, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [row("MB-B550M", installed_in="llm", location="llm")],
        },
        [],
    )
    module = stores["module"][0]
    assert module.parent_module_bay is None
    assert module.location.name == "llm"
    assert any("no such Device" in w for w in job.logger.warnings), job.logger.warnings
    assert not stores["device"], "must never invent a placeholder chassis"

    # Re-running must not duplicate: same asset_tag, same object.
    seed = {"hardware_devices": [], "hardware_modules": [row("GPU-SPARE")]}
    _, stores = run(seed, [r540])
    assert len(stores["module"]) == 1

    # A chassis row the rack-server seed owns is left alone.
    job, stores = run(
        {
            "hardware_devices": [
                row("SRV-R540", category="Server", installed_in="r540", location="r540")
            ],
            "hardware_modules": [],
        },
        [r540],
    )
    assert stores["device"] == [r540], "must not create a second object for one chassis"
    assert any("rack-server seed owns" in i for i in job.logger.infos), job.logger.infos

    # A standalone chassis IS created, named by its hardware id.
    _, stores = run(
        {
            "hardware_devices": [
                row("UNI-UDW", category="All-in-one", location="active", installed_in=None)
            ],
            "hardware_modules": [],
        },
        [],
    )
    assert len(stores["device"]) == 1 and stores["device"][0].name == "UNI-UDW"

    # A dry run writes nothing.
    _, stores = run(
        {"hardware_devices": [], "hardware_modules": [row("GPU-DRY")]}, [], dryrun=True
    )
    assert not stores["module"], "dryrun must not create objects"

    # WAN circuits: a Planned uplink must not be published Active, and nothing
    # invents a termination for a link whose endpoint is not recorded.
    _, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [],
            "wan_circuits": [
                {
                    "circuit_id": "WAN1-XFINITY",
                    "provider": "Xfinity",
                    "circuit_type": "Cable",
                    "priority": 1,
                    "status": "Active",
                    "description": "Cable — primary",
                },
                {
                    "circuit_id": "WAN2-STARLINK",
                    "provider": "Starlink",
                    "circuit_type": "Satellite",
                    "priority": 2,
                    "status": "Planned",
                    "description": "Satellite — secondary",
                },
            ],
        },
        [],
    )
    by_cid = {c.cid: c for c in stores["circuit"]}
    assert set(by_cid) == {"WAN1-XFINITY", "WAN2-STARLINK"}
    assert by_cid["WAN2-STARLINK"].status.name == "Planned", "a planned link must not read live"
    assert by_cid["WAN1-XFINITY"].status.name == "Active"
    assert not any(hasattr(c, "termination_a") for c in stores["circuit"])

    # An absent slice is a warning and a no-op, not a crash.
    job, stores = run({"hardware_devices": [], "hardware_modules": []}, [])
    assert not stores["module"] and not stores["device"]
    assert any("no hardware slice" in w for w in job.logger.warnings), job.logger.warnings

    print("nautobot_hardware_seed: OK")


if __name__ == "__main__":
    main()
