"""SSoT seed job: DCIM racks and devices (issue #138).

Source of truth: the ``racks`` and ``devices`` arrays of the seed bundle (from
``terraform-proxmox`` SOPS ``rack_servers``). DiffSyncs Racks, Devices (with a
DeviceType per distinct chassis under the Generic manufacturer, a Role, the
homelab Location, optional rack/position, serial = service_tag) and a mgmt-only
``BMC`` Interface per device.

Live-validation notes: DeviceTypes/Roles are ensured via the ORM before the
DiffSync run; binding the BMC IP address to the BMC interface is deferred to
Device Onboarding to avoid the generic-FK path here.
"""
from __future__ import annotations

from typing import Optional

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.dcim.models import Device, Interface, Rack
from nautobot_ssot.contrib import NautobotAdapter
from nautobot_ssot.jobs.base import DataSource

from ssot_common import (
    STATUS_ACTIVE,
    AdditiveNautobotModel,
    ensure_device_type,
    ensure_location,
    ensure_role,
    load_seed,
)

BMC_INTERFACE_NAME = "BMC"
SERVER_ROLE = "server"


class RackModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot Rack."""

    _model = Rack
    _modelname = "rack"
    _identifiers = ("name",)
    _attributes = ("location__name", "status__name")

    name: str
    location__name: str
    status__name: str


class DeviceModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot Device."""

    _model = Device
    _modelname = "device"
    _identifiers = ("name",)
    _attributes = (
        "role__name",
        "device_type__model",
        "location__name",
        "status__name",
        "rack__name",
        "position",
        "serial",
    )

    name: str
    role__name: str
    device_type__model: str
    location__name: str
    status__name: str
    rack__name: Optional[str] = None
    position: Optional[int] = None
    serial: str = ""

    @classmethod
    def get_queryset(cls):
        """Exclude pve nodes — the node seed job owns those devices."""
        return Device.objects.exclude(role__name="pve-node")


class InterfaceModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot Interface (the BMC port)."""

    _model = Interface
    _modelname = "interface"
    _identifiers = ("device__name", "name")
    _attributes = ("type", "mgmt_only", "status__name")

    device__name: str
    name: str
    type: str
    mgmt_only: bool
    status__name: str

    @classmethod
    def get_queryset(cls):
        """Manage only BMC interfaces so other interfaces are never diffed."""
        return Interface.objects.filter(name=BMC_INTERFACE_NAME)


class DcimNautobotAdapter(NautobotAdapter):
    """Target adapter: loads existing Racks/Devices/Interfaces from Nautobot."""

    top_level = ("rack", "device", "interface")
    rack = RackModel
    device = DeviceModel
    interface = InterfaceModel


class DcimSourceAdapter(Adapter):
    """Source adapter: builds Rack/Device/Interface models from the seed."""

    top_level = ("rack", "device", "interface")
    rack = RackModel
    device = DeviceModel
    interface = InterfaceModel

    def __init__(self, *args, job=None, **kwargs):
        """Store the owning Job for logging."""
        super().__init__(*args, **kwargs)
        self.job = job

    def load(self) -> None:
        """Populate Rack/Device/Interface models from the seed bundle."""
        seed = load_seed()

        for rack in seed["racks"]:
            self.add(
                self.rack(
                    name=str(rack["name"]),
                    location__name=str(rack.get("site") or "homelab"),
                    status__name=STATUS_ACTIVE,
                )
            )

        for device in seed["devices"]:
            chassis = str(device.get("chassis") or "unknown")
            role = str(device.get("role") or SERVER_ROLE)
            ensure_device_type(chassis)
            ensure_role(role, Device)

            position = device.get("position")
            self.add(
                self.device(
                    name=str(device["name"]),
                    role__name=role,
                    device_type__model=chassis,
                    location__name="homelab",
                    status__name=STATUS_ACTIVE,
                    rack__name=str(device["rack"]) if device.get("rack") else None,
                    position=int(position) if position is not None else None,
                    serial=str(device.get("service_tag") or ""),
                )
            )

            if device.get("bmc_ip") or device.get("bmc_mac"):
                self.add(
                    self.interface(
                        device__name=str(device["name"]),
                        name=BMC_INTERFACE_NAME,
                        type="other",
                        mgmt_only=True,
                        status__name=STATUS_ACTIVE,
                    )
                )


class SeedDcim(DataSource):
    """Seed Nautobot DCIM racks and devices from the rack-server source."""

    class Meta:
        """Job metadata."""

        name = "Seed DCIM Racks and Devices"
        description = "DiffSync racks, devices, and BMC interfaces from the seed bundle."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Ensure org scaffolding, then load the seed source adapter."""
        ensure_location()
        self.source_adapter = DcimSourceAdapter(job=self)
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the Nautobot target adapter."""
        self.target_adapter = DcimNautobotAdapter(job=self)
        self.target_adapter.load()


register_jobs(SeedDcim)
