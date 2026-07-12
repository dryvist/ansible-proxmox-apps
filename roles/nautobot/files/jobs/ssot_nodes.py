"""SSoT seed job: Proxmox VE node facts (issue #138).

Source of truth: the ``nodes`` array of the seed bundle (from ``ansible-proxmox``
``hosts.yml``). DiffSyncs the commissioned pve nodes into Nautobot Devices with
role ``pve-node`` and a ``pve-node`` DeviceType under the Generic manufacturer.
Uncommissioned nodes are skipped.

Live-validation notes: like the DCIM job, DeviceType/Role are ensured via the
ORM before the DiffSync run; mgmt-IP-to-interface binding is deferred to Device
Onboarding.
"""
from __future__ import annotations

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.dcim.models import Device
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

NODE_ROLE = "pve-node"
NODE_DEVICE_TYPE = "pve-node"


class NodeDeviceModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot Device for a Proxmox node.

    Scoped to node-role devices so the target adapter only ever loads (and thus
    only ever updates) the pve nodes — the DCIM seed job owns the other devices.
    """

    @classmethod
    def get_queryset(cls):
        """Load only pve-node-role devices into the target adapter."""
        return Device.objects.filter(role__name=NODE_ROLE)

    _model = Device
    _modelname = "device"
    _identifiers = ("name",)
    _attributes = ("role__name", "device_type__model", "location__name", "status__name")

    name: str
    role__name: str
    device_type__model: str
    location__name: str
    status__name: str


class NodesNautobotAdapter(NautobotAdapter):
    """Target adapter: loads existing node Devices from the Nautobot ORM.

    Scoping lives on ``NodeDeviceModel.get_queryset`` (node-role only), so this
    adapter only diffs pve nodes.
    """

    top_level = ("device",)
    device = NodeDeviceModel


class NodesSourceAdapter(Adapter):
    """Source adapter: builds node Device models from the seed bundle."""

    top_level = ("device",)
    device = NodeDeviceModel

    def __init__(self, *args, job=None, **kwargs):
        """Store the owning Job for logging."""
        super().__init__(*args, **kwargs)
        self.job = job

    def load(self) -> None:
        """Populate node Device models from the seed bundle (commissioned only)."""
        seed = load_seed()
        ensure_device_type(NODE_DEVICE_TYPE)
        ensure_role(NODE_ROLE, Device)
        for node in seed["nodes"]:
            if not node.get("commissioned", True):
                continue
            self.add(
                self.device(
                    name=str(node["name"]),
                    role__name=NODE_ROLE,
                    device_type__model=NODE_DEVICE_TYPE,
                    location__name="homelab",
                    status__name=STATUS_ACTIVE,
                )
            )


class SeedNodes(DataSource):
    """Seed Nautobot with the Proxmox VE node inventory."""

    class Meta:
        """Job metadata."""

        name = "Seed Proxmox Node Facts"
        description = "DiffSync commissioned Proxmox nodes from the seed bundle."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Ensure org scaffolding, then load the seed source adapter."""
        ensure_location()
        self.source_adapter = NodesSourceAdapter(job=self)
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the Nautobot target adapter."""
        self.target_adapter = NodesNautobotAdapter(job=self)
        self.target_adapter.load()


register_jobs(SeedNodes)
