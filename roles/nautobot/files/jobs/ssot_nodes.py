"""SSoT seed job: Proxmox VE node facts (issue #138).

Source of truth: the ``nodes`` array of the seed bundle (from ``ansible-proxmox``
``hosts.yml``). DiffSyncs the commissioned pve nodes into Nautobot Devices with
role ``pve-node`` and a ``pve-node`` DeviceType under the Generic manufacturer.

Uncommissioned nodes are skipped, and that skip is live: the bundle reads each
node's ``commissioned`` flag from the desired-state object, keyed by the live
node name, and defaults to true only where the object does not carry the node.
A node the desired-state object marks uncommissioned therefore never reaches
this job, which is what keeps a deliberately decommissioned Device from being
flipped back to Active by the managed ``status__name`` attribute.

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
# Seeded only when Nautobot has no Device for the node yet; see NodesSourceAdapter.load.
DEFAULT_LOCATION = "homelab"


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
        """Populate node Device models from the seed bundle (commissioned only).

        `device_type` and `location` are seeded ONLY for a node Nautobot does not
        already have. Where a Device already exists, its current values are
        carried into the source model so the diff is empty for those fields.

        This job knows a node's NAME, not its hardware. Emitting the placeholder
        type and the default location unconditionally makes them managed
        attributes, so DiffSync would "correct" curated values back down to
        them — turning a real chassis model into the literal placeholder and
        moving the device to the default location. That is silent data loss in
        the system of record, and it is triggered by an ordinary rename, since
        these models are identified by name alone.

        Status stays managed: a node the seed calls commissioned is expected to
        be active, and that is an assertion this job is entitled to make.
        """
        seed = load_seed()
        ensure_device_type(NODE_DEVICE_TYPE)
        ensure_role(NODE_ROLE, Device)
        curated = {
            device.name: device
            for device in Device.objects.filter(role__name=NODE_ROLE).select_related(
                "device_type", "location"
            )
        }
        for node in seed["nodes"]:
            if not node.get("commissioned", True):
                continue
            name = str(node["name"])
            existing = curated.get(name)
            self.add(
                self.device(
                    name=name,
                    role__name=NODE_ROLE,
                    device_type__model=(
                        existing.device_type.model if existing else NODE_DEVICE_TYPE
                    ),
                    location__name=(
                        existing.location.name if existing else DEFAULT_LOCATION
                    ),
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
