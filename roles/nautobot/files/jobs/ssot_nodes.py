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
ORM before the DiffSync run. Management-IP binding is done HERE, in an additive
ORM phase -- see SeedNodes._bind_primary_ips. An earlier revision deferred it to
Device Onboarding, which never covered these devices: SSOTSyncDevices sweeps
SSH-CLI network platforms and Proxmox is explicitly out of scope for it, so
primary_ip4 stayed null on every node indefinitely with nothing erroring.
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
# Name of the management Interface this job binds the node address to. "BMC" is
# taken by the DCIM job for out-of-band interfaces; this is the in-band one.
MGMT_INTERFACE_NAME = "mgmt"


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
        seed_names = {
            str(node["name"])
            for node in seed["nodes"]
            if node.get("commissioned", True)
        }
        # Refuse a rename. These models are identified by NAME alone and
        # `delete` is a deliberate no-op, so a name change is not a move: the
        # new name is created and the old Device is left orphaned beside it,
        # silently, at rc=0. Nothing later cleans it up.
        #
        # The signature is specific — some seed names would be created AND some
        # existing Devices would be left unmatched. A genuinely new node only
        # produces the first, and a removed node only the second, so neither is
        # blocked here.
        would_create = seed_names - curated.keys()
        would_strand = curated.keys() - seed_names
        if curated and would_create and would_strand:
            raise ValueError(
                "Refusing to seed: this looks like a node rename, which this job "
                "cannot perform. It would CREATE "
                f"{sorted(would_create)} while leaving {sorted(would_strand)} "
                "orphaned, because these devices are identified by name alone "
                "and delete is a no-op. Rename the device in the system of "
                "record first so the names match, then re-run. If a node was "
                "genuinely added and another genuinely removed in the same "
                "change, split them into separate runs."
            )

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

    def run(self, *args, **kwargs):  # noqa: D102 - see _bind_primary_ips
        """Run the additive node sync, then bind each node's management IP."""
        super().run(*args, **kwargs)
        self._bind_primary_ips()

    def _bind_primary_ips(self) -> None:
        """Ensure a mgmt interface + assigned IPAddress + primary_ip4 per node.

        ORM (not DiffSync): the interface assignment and the primary-IP FK are
        the generic-FK path DiffSync defers, exactly as
        ``ssot_virtualization.py::_bind_primary_ips`` does for guests.

        This job's docstring used to say mgmt-IP binding was "deferred to Device
        Onboarding". It is not, and never was: ``schedule_discovery.py`` states
        that SSOTSyncDevices sweeps SSH-CLI (netmiko) network platforms and that
        "Proxmox / iDRAC / UniFi discovery via native APIs is a tracked
        follow-up, not this job." Proxmox nodes are out of scope for it by
        design, so nothing was ever going to set primary_ip4 for them and every
        pve Device sat with it null.

        The address is NOT invented here and no address is added to the desired
        state. It is matched against the IPAddress objects
        ``ssot_ip_addresses.py`` already seeds from the fixed-IP reservations,
        by ``dns_name``. That keeps the estate's "no literal IPs" rule intact:
        the only thing this job knows is a NAME.
        """
        from nautobot.dcim.models import Interface
        from nautobot.extras.models import Status
        from nautobot.ipam.models import IPAddress, IPAddressToInterface

        status = Status.objects.get(name=STATUS_ACTIVE)
        seed = load_seed()
        commissioned = [n for n in seed["nodes"] if n.get("commissioned", True)]
        bound = 0

        for node in commissioned:
            # The record's name, which may differ from the key -- the same field
            # the source adapter uses. Matching on the wrong one is how a rename
            # strands a Device beside a duplicate.
            name = str(node.get("nautobot_device_name") or node.get("name") or "")
            if not name:
                continue
            device = Device.objects.filter(name=name).first()
            if device is None:  # not created (e.g. dry run) -- nothing to bind
                continue
            ip_address = IPAddress.objects.filter(dns_name=name).first()
            if ip_address is None:
                # Loud per node: a commissioned node with no seeded reservation
                # is a real gap, not a shrug. Silence here is what let this sit
                # broken indefinitely in the first place.
                self.logger.warning(
                    "No seeded IPAddress with dns_name=%s; %s keeps primary_ip4 "
                    "unset. Add a fixed-IP reservation carrying that dns_name.",
                    name,
                    name,
                )
                continue
            interface, _ = Interface.objects.get_or_create(
                device=device,
                name=MGMT_INTERFACE_NAME,
                defaults={"type": "other", "mgmt_only": True, "status": status},
            )
            IPAddressToInterface.objects.get_or_create(
                ip_address=ip_address, interface=interface
            )
            if device.primary_ip4_id != ip_address.id:
                device.primary_ip4 = ip_address
                device.validated_save()
            bound += 1

        # A per-node warning is invisible in a green run, so assert the SET.
        # Zero matches across every commissioned node is not "nothing to do" --
        # it is the signature of the reservation dns_names and the Device names
        # having drifted apart, and it must fail rather than report success.
        # Mirrors load_tofu.yml's "Assert the node_storage lookup matched at
        # least one host", which exists for exactly this failure shape.
        if commissioned and Device.objects.filter(role__name=NODE_ROLE).exists() and not bound:
            raise ValueError(
                f"Bound primary_ip4 for 0 of {len(commissioned)} commissioned "
                "nodes. Every lookup missed, which means the seeded reservation "
                "dns_names and the Nautobot Device names have drifted apart -- "
                "not that there was nothing to do. Reconcile the names (see "
                "`nautobot_device_name`) rather than letting this pass green."
            )


register_jobs(SeedNodes)
