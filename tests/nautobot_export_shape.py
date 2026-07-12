"""Fixture check for the Nautobot export contract shape."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPORT_JOB = ROOT / "roles/nautobot/files/jobs/export_nautobot.py"
SCHEMA = ROOT / "roles/nautobot/files/contracts/nautobot-export-v1.json"


class Manager(list):
    """Tiny stand-in for a Django model manager."""

    def all(self) -> list[Any]:
        """Return all stored objects."""
        return list(self)


class Related(list):
    """Tiny stand-in for a Django related manager."""

    def all(self) -> list[Any]:
        """Return all related objects."""
        return list(self)


class Object:
    """Simple object with named attributes."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class VLAN:
    """Fake Nautobot VLAN model."""


class Prefix:
    """Fake Nautobot Prefix model."""


class IPAddress:
    """Fake Nautobot IPAddress model."""


class Device:
    """Fake Nautobot Device model."""


class Interface:
    """Fake Nautobot Interface model."""


class Rack:
    """Fake Nautobot Rack model."""


def install_import_stubs() -> None:
    """Install enough modules for importing the Nautobot job file."""
    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *_args, **_kwargs: None
    sys.modules["boto3"] = boto3

    jobs = types.ModuleType("nautobot.apps.jobs")
    jobs.Job = object
    jobs.register_jobs = lambda *_args, **_kwargs: None

    dcim_models = types.ModuleType("nautobot.dcim.models")
    dcim_models.Device = Device
    dcim_models.Interface = Interface
    dcim_models.Rack = Rack

    ipam_models = types.ModuleType("nautobot.ipam.models")
    ipam_models.VLAN = VLAN
    ipam_models.IPAddress = IPAddress
    ipam_models.Prefix = Prefix

    for name in (
        "nautobot",
        "nautobot.apps",
        "nautobot.dcim",
        "nautobot.ipam",
    ):
        sys.modules[name] = types.ModuleType(name)
    sys.modules["nautobot.apps.jobs"] = jobs
    sys.modules["nautobot.dcim.models"] = dcim_models
    sys.modules["nautobot.ipam.models"] = ipam_models


def load_export_module() -> Any:
    """Import the export job module with fake Nautobot dependencies."""
    install_import_stubs()
    spec = importlib.util.spec_from_file_location("export_nautobot", EXPORT_JOB)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def main() -> None:
    """Build a sample export and validate its contract shape."""
    module = load_export_module()

    vlan_group = Object(name="example-group")
    VLAN.objects = Manager([Object(vid=10, name="example-mgmt", vlan_group=vlan_group)])

    Prefix.objects = Manager(
        [Object(prefix="192.0.2.0/24", vlan_id=1, vlan=Object(vid=10), role=Object(name="mgmt"))]
    )

    rack = Object(name="rack-1", location=Object(name="example-site"), u_height=42)
    Rack.objects = Manager([rack])

    device = Object(name="example-node-1", role=Object(name="server"), rack=rack)
    bmc_interface = Object(
        device=device,
        name="BMC",
        mac_address="02:00:00:00:00:60",
        type="other",
        mgmt_only=True,
    )
    primary_interface = Object(
        device=device,
        name="eth0",
        mac_address="02:00:00:00:00:10",
        type="1000base-t",
        mgmt_only=False,
    )
    bmc_ip = Object(address="192.0.2.60/24")
    primary_ip = Object(
        address="192.0.2.10/24",
        dns_name="node-1.example.com",
        interfaces=Related([primary_interface]),
    )
    bmc_interface.ip_addresses = Related([bmc_ip])
    primary_interface.ip_addresses = Related([primary_ip])
    device.interfaces = Related([bmc_interface, primary_interface])

    Device.objects = Manager([device])
    Interface.objects = Manager([bmc_interface, primary_interface])
    IPAddress.objects = Manager([primary_ip])

    document = module.build_export()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    required = schema["required"]

    assert list(document) == required, list(document)
    defs_by_collection = {
        "vlans": "vlan",
        "prefixes": "prefix",
        "ip_addresses": "ipAddress",
        "devices": "device",
        "racks": "rack",
        "interfaces": "interface",
    }
    for collection in required[1:]:
        expected_item_keys = schema["$defs"][defs_by_collection[collection]]["required"]
        assert list(document[collection][0]) == expected_item_keys, document[collection][0]

    jsonschema_status = "skipped"
    try:
        import jsonschema
    except ModuleNotFoundError:
        pass
    else:
        jsonschema.validate(instance=document, schema=schema)
        jsonschema_status = "validated"

    print("export_shape_ok", ",".join(document.keys()), f"jsonschema={jsonschema_status}")


if __name__ == "__main__":
    main()
