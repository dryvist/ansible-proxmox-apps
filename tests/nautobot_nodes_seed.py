"""Behaviour check for the node seed job (roles/nautobot/files/jobs/ssot_nodes.py).

Stubs django/nautobot the way tests/nautobot_hardware_seed.py does, so the job's
real load() logic runs without a Nautobot install.

What is pinned down here is the one thing that is silently destructive: these
models are identified by NAME alone, so a node rename makes the job look at a
Device it has never seen before. If it emitted its placeholder device type and
default location unconditionally, DiffSync would treat curated values as drift
and write the placeholders over them — losing the real chassis model and
location from the system of record, with no error and no diff to review.

So: an already-known node keeps its curated device_type and location, and only a
genuinely new node gets the seeded defaults.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / "roles/nautobot/files/jobs"


class Record:
    """An object with named attributes, standing in for a model instance."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class FakeQuerySet(list):
    """List with the queryset method the job chains onto filter()."""

    def select_related(self, *_args):
        """Ignore prefetch hints; the fakes are already whole objects."""
        return self


class FakeDeviceManager:
    """Minimal Django manager: only the filter() the job actually calls."""

    def __init__(self, store: list[Record]) -> None:
        self.store = store

    def filter(self, **kwargs):
        """Return the records matching every supplied lookup."""
        return FakeQuerySet(
            [
                item
                for item in self.store
                if all(_lookup(item, key) == value for key, value in kwargs.items())
            ]
        )


def _lookup(item: Record, key: str) -> Any:
    """Resolve a Django-style `a__b` lookup against a fake record."""
    value: Any = item
    for part in key.split("__"):
        value = getattr(value, part, None)
    return value


def load_job(devices: list[Record], nodes: list[dict[str, Any]]):
    """Install stubs, import ssot_nodes fresh, and return the module."""
    device_cls = type("Device", (), {"objects": FakeDeviceManager(devices)})

    dcim = types.ModuleType("nautobot.dcim.models")
    dcim.Device = device_cls

    nautobot = types.ModuleType("nautobot")
    apps_jobs = types.ModuleType("nautobot.apps.jobs")
    apps_jobs.register_jobs = lambda *_a, **_k: None

    class _Adapter:
        """Stand-in for diffsync.Adapter that just collects added models."""

        def __init__(self, *_a, **_k) -> None:
            self.added: list[Any] = []

        def add(self, model):
            """Record the model the job emitted."""
            self.added.append(model)

    diffsync = types.ModuleType("diffsync")
    diffsync.Adapter = _Adapter

    ssot_contrib = types.ModuleType("nautobot_ssot.contrib")
    ssot_contrib.NautobotAdapter = _Adapter
    ssot_base = types.ModuleType("nautobot_ssot.jobs.base")
    ssot_base.DataSource = type("DataSource", (), {})

    class _Model:
        """Stand-in for the pydantic-ish DiffSync model base."""

        def __init__(self, **attrs: Any) -> None:
            self.__dict__.update(attrs)

    common = types.ModuleType("ssot_common")
    common.STATUS_ACTIVE = "Active"
    common.AdditiveNautobotModel = _Model
    common.ensure_device_type = lambda *_a, **_k: None
    common.ensure_location = lambda *_a, **_k: None
    common.ensure_role = lambda *_a, **_k: None
    common.load_seed = lambda: {"nodes": nodes}

    for name, module in {
        "nautobot": nautobot,
        "nautobot.apps": types.ModuleType("nautobot.apps"),
        "nautobot.apps.jobs": apps_jobs,
        "nautobot.dcim": types.ModuleType("nautobot.dcim"),
        "nautobot.dcim.models": dcim,
        "nautobot_ssot": types.ModuleType("nautobot_ssot"),
        "nautobot_ssot.contrib": ssot_contrib,
        "nautobot_ssot.jobs": types.ModuleType("nautobot_ssot.jobs"),
        "nautobot_ssot.jobs.base": ssot_base,
        "diffsync": diffsync,
        "ssot_common": common,
    }.items():
        sys.modules[name] = module

    sys.modules.pop("ssot_nodes", None)
    spec = importlib.util.spec_from_file_location("ssot_nodes", JOBS / "ssot_nodes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ssot_nodes"] = module
    spec.loader.exec_module(module)
    return module


def _emit(devices, nodes):
    """Run the source adapter's load() and return the emitted models by name."""
    module = load_job(devices, nodes)
    adapter = module.NodesSourceAdapter()
    adapter.device = module.NodeDeviceModel
    adapter.load()
    return {model.name: model for model in adapter.added}


def test_curated_device_fields_are_preserved() -> None:
    """A node Nautobot already knows keeps its real chassis model and location."""
    devices = [
        Record(
            name="pve-r710",
            device_type=Record(model="PowerEdge R710"),
            location=Record(name="server room"),
            role=Record(name="pve-node"),
        )
    ]
    emitted = _emit(devices, [{"name": "pve-r710", "commissioned": True}])

    model = emitted["pve-r710"]
    assert model.device_type__model == "PowerEdge R710", model.device_type__model
    assert model.location__name == "server room", model.location__name
    assert model.status__name == "Active", model.status__name


def test_unknown_node_gets_the_seeded_defaults() -> None:
    """A node with no Device yet is still created, with the placeholder type."""
    emitted = _emit([], [{"name": "pve-brand-new", "commissioned": True}])

    model = emitted["pve-brand-new"]
    assert model.device_type__model == "pve-node", model.device_type__model
    assert model.location__name == "homelab", model.location__name


def test_uncommissioned_node_is_skipped() -> None:
    """An uncommissioned node is never emitted, so its Device is left alone."""
    devices = [
        Record(
            name="pve-r410",
            device_type=Record(model="PowerEdge R410"),
            location=Record(name="server room"),
            role=Record(name="pve-node"),
        )
    ]
    emitted = _emit(devices, [{"name": "pve-r410", "commissioned": False}])

    assert emitted == {}, emitted


def _curated(*names: str) -> list[Record]:
    """Existing node-role Devices, one per supplied name."""
    return [
        Record(
            name=name,
            device_type=Record(model="PowerEdge"),
            location=Record(name="server room"),
            role=Record(name="pve-node"),
        )
        for name in names
    ]


def test_rename_is_refused() -> None:
    """A rename creates the new name and orphans the old one, so it is refused.

    This is the destructive case these models cannot express: they are keyed on
    name alone and delete is a no-op, so DiffSync turns a rename into a create
    plus a stranded Device, silently, at rc=0.
    """
    devices = _curated("node-old-name", "node-unchanged")
    nodes = [
        {"name": "node-new-name", "commissioned": True},
        {"name": "node-unchanged", "commissioned": True},
    ]
    try:
        _emit(devices, nodes)
    except ValueError as exc:
        message = str(exc)
        assert "node-new-name" in message, message
        assert "node-old-name" in message, message
    else:
        raise AssertionError("a rename must be refused, not seeded")


def test_pure_addition_and_pure_removal_are_allowed() -> None:
    """Adding a node, or removing one, is not a rename and must still seed.

    Only the combination — something created AND something stranded — is the
    rename signature, so neither of these may trip the guard.
    """
    added = _emit(_curated("node-existing"), [
        {"name": "node-existing", "commissioned": True},
        {"name": "node-additional", "commissioned": True},
    ])
    assert set(added) == {"node-existing", "node-additional"}, added

    removed = _emit(_curated("node-existing", "node-retired"), [
        {"name": "node-existing", "commissioned": True},
    ])
    assert set(removed) == {"node-existing"}, removed


if __name__ == "__main__":
    ran = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            ran += 1
            print(f"PASS {name}")
    print(f"\n{ran} assertions groups passed")
    assert ran == 5, f"expected 5 tests, ran {ran}"
