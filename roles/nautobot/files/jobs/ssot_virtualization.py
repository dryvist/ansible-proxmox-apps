"""SSoT seed job: Proxmox VE guests as Virtualization objects (issue #138).

Source of truth: the ``virtual_machines`` array of the seed bundle (folded from
the resolved tofu inventory — every LXC container, VM, docker VM, and the Splunk
VM). DiffSyncs each guest into a Nautobot VirtualMachine (role Active, cluster =
its Proxmox node, role = its first tag) additively. A ClusterType ``Proxmox`` and
one Cluster per distinct node are ensured via the ORM before the DiffSync run,
mirroring how the DCIM/node jobs ensure their DeviceType/Role scaffolding.

After the additive VM sync, each guest carrying a numeric address gets an
``eth0`` VMInterface, an IPAddress assigned to it, and that IP set as the VM's
``primary_ip4`` — done in an ORM phase (not DiffSync) because the interface
assignment and primary-IP FK are the generic-FK path the sibling jobs already
defer out of DiffSync. IPAddress creation reuses the reservation job's approach
(a /32 under an existing parent Prefix); a guest whose address has no parent
Prefix (run the VLANs/Prefixes seed first) is skipped, never fatal.

Live-validation notes: exact Nautobot 2.x field names on VirtualMachine /
VMInterface / IPAddressToInterface target current 2.x.
"""
from __future__ import annotations

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.virtualization.models import VirtualMachine
from nautobot_ssot.contrib import NautobotAdapter
from nautobot_ssot.jobs.base import DataSource

from ssot_common import (
    STATUS_ACTIVE,
    AdditiveNautobotModel,
    ensure_location,
    ensure_role,
    ensure_tag,
    load_seed,
)

CLUSTER_TYPE = "Proxmox"
DEFAULT_CLUSTER = "unknown"
DEFAULT_ROLE = "vm"
INTERFACE_NAME = "eth0"
# Proxmox guest id. Nautobot has no native field for it, so it rides in a custom
# field — the export job reads this same key.
VMID_FIELD = "vmid"
# Nautobot's own IPAddress.type value for an address held by DHCP reservation.
DEFAULT_IP_TYPE = "host"


def _active_status():
    """Return the shipped ``Active`` Status object."""
    from nautobot.extras.models import Status

    return Status.objects.get(name=STATUS_ACTIVE)


def ensure_vmid_field():
    """Idempotently ensure the ``vmid`` custom field exists on VirtualMachine.

    Mirrors how the sibling jobs ensure their DeviceType/Role scaffolding via the
    ORM before the DiffSync run. Integer-typed so consumers get a number, not a
    stringly-typed id.
    """
    from django.contrib.contenttypes.models import ContentType
    from nautobot.extras.models import CustomField

    field, _ = CustomField.objects.get_or_create(
        key=VMID_FIELD,
        defaults={"label": "VMID", "type": "integer"},
    )
    field.content_types.add(ContentType.objects.get_for_model(VirtualMachine))
    return field


def ensure_cluster(name: str):
    """Idempotently ensure the ``Proxmox`` ClusterType and a Cluster (by node)."""
    from nautobot.virtualization.models import Cluster, ClusterType

    cluster_type, _ = ClusterType.objects.get_or_create(name=CLUSTER_TYPE)
    cluster, _ = Cluster.objects.get_or_create(
        name=name, defaults={"cluster_type": cluster_type}
    )
    return cluster


class VirtualMachineModel(AdditiveNautobotModel):
    """DiffSync model mirroring a Nautobot VirtualMachine."""

    _model = VirtualMachine
    _modelname = "virtual_machine"
    _identifiers = ("name",)
    _attributes = ("cluster__name", "status__name", "role__name")

    name: str
    cluster__name: str
    status__name: str
    role__name: str


class VirtualizationNautobotAdapter(NautobotAdapter):
    """Target adapter: loads existing VirtualMachines from the Nautobot ORM."""

    top_level = ("virtual_machine",)
    virtual_machine = VirtualMachineModel


class VirtualizationSourceAdapter(Adapter):
    """Source adapter: builds VirtualMachine models from the seed bundle."""

    top_level = ("virtual_machine",)
    virtual_machine = VirtualMachineModel

    def __init__(self, *args, job=None, **kwargs):
        """Store the owning Job for logging."""
        super().__init__(*args, **kwargs)
        self.job = job

    def load(self) -> None:
        """Populate VirtualMachine models from the seed bundle (guests only)."""
        seed = load_seed()
        for guest in seed["virtual_machines"]:
            name = str(guest.get("name") or "")
            if not name:
                continue
            cluster = str(guest.get("cluster") or DEFAULT_CLUSTER)
            role = str(guest.get("role") or DEFAULT_ROLE)
            ensure_cluster(cluster)
            ensure_role(role, VirtualMachine)
            self.add(
                self.virtual_machine(
                    name=name,
                    cluster__name=cluster,
                    status__name=STATUS_ACTIVE,
                    role__name=role,
                )
            )


class SeedVirtualization(DataSource):
    """Seed Nautobot with the Proxmox VE guests as Virtualization objects."""

    class Meta:
        """Job metadata."""

        name = "SSoT: Virtualization (Proxmox guests)"
        description = "DiffSync Proxmox guests into Nautobot VirtualMachines from the seed bundle."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Ensure org scaffolding, then load the seed source adapter."""
        ensure_location()
        ensure_vmid_field()
        self.source_adapter = VirtualizationSourceAdapter(job=self)
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the Nautobot target adapter."""
        self.target_adapter = VirtualizationNautobotAdapter(job=self)
        self.target_adapter.load()

    def run(self, *args, **kwargs):  # noqa: D102 - see _bind_primary_ips
        """Run the additive VM sync, then bind eth0 + primary IP + vmid + tags."""
        super().run(*args, **kwargs)
        self._bind_primary_ips()
        self._bind_vmids()
        self._bind_tags()

    def _bind_vmids(self) -> None:
        """Store each guest's Proxmox vmid in its ``vmid`` custom field.

        Its own ORM phase rather than folded into ``_bind_primary_ips`` because
        that method skips any guest without a numeric address — a guest with no
        IP still has a vmid, and the export needs it. Non-numeric or absent vmids
        are skipped, never fatal.
        """
        for guest in load_seed()["virtual_machines"]:
            name = str(guest.get("name") or "")
            if not name:
                continue
            try:
                vmid = int(guest.get("vmid"))
            except (TypeError, ValueError):
                continue
            vm = VirtualMachine.objects.filter(name=name).first()
            if vm is None:  # not created (e.g. dry run) — nothing to stamp
                continue
            if vm.custom_field_data.get(VMID_FIELD) != vmid:
                vm.custom_field_data[VMID_FIELD] = vmid
                vm.validated_save()

    def _bind_primary_ips(self) -> None:
        """Ensure eth0 + an assigned IPAddress + primary_ip4 for each guest.

        ORM (not DiffSync): the interface assignment and primary-IP FK are the
        generic-FK path the sibling jobs defer. Additive and per-guest defensive
        — a guest whose IP has no parent Prefix (VLANs/Prefixes seed not yet run)
        or whose ``ip`` is not numeric (a stray FQDN) is skipped, never fatal.
        """
        from nautobot.ipam.models import IPAddress, IPAddressToInterface
        from nautobot.virtualization.models import VMInterface

        status = _active_status()
        for guest in load_seed()["virtual_machines"]:
            name = str(guest.get("name") or "")
            host = str(guest.get("ip") or "").split("/", 1)[0]
            if not name or not host:
                continue
            vm = VirtualMachine.objects.filter(name=name).first()
            if vm is None:  # not created (e.g. dry run) — nothing to bind
                continue
            # 'dhcp' when the guest holds its address by reservation, else
            # 'host'. Carried from the seed so the static-vs-reserved
            # distinction reaches Nautobot and, from there, the export.
            ip_type = str(guest.get("ip_type") or DEFAULT_IP_TYPE)
            try:
                ip_address, created = IPAddress.objects.get_or_create(
                    host=host,
                    defaults={"mask_length": 32, "status": status, "type": ip_type},
                )
            except Exception as exc:  # noqa: BLE001 - stay additive on any IP error
                self.logger.warning("Skipped IP for VM %s: %s", name, exc)
                continue
            # Correct the type on an address seeded before it was tracked.
            if not created and ip_address.type != ip_type:
                ip_address.type = ip_type
                ip_address.validated_save()
            interface, _ = VMInterface.objects.get_or_create(
                virtual_machine=vm, name=INTERFACE_NAME, defaults={"status": status}
            )
            IPAddressToInterface.objects.get_or_create(
                ip_address=ip_address, vm_interface=interface
            )
            if vm.primary_ip4_id != ip_address.id:
                vm.primary_ip4 = ip_address
                vm.validated_save()

    def _bind_tags(self) -> None:
        """Assign each guest's tofu tags to its VirtualMachine (additive ORM phase).

        Tags drive the GraphQL dynamic inventory group construction
        (``inventory/nautobot.yml`` keys its ``*_group`` mapping on ``tags:name``),
        so the seed must import them (issue #1008). DiffSync avoids m2m, so tags
        are applied here like the primary-IP FK. Additive: tags are only added,
        never removed, matching the additive seed contract.
        """
        guests = load_seed()["virtual_machines"]

        def _valid_names(guest) -> list[str]:
            """The guest's non-empty tag names, dropping None (never ``'None'``)."""
            return [str(tag) for tag in (guest.get("tags") or []) if tag and str(tag)]

        # Ensure each distinct tag once (get_or_create is idempotent but not free)
        # rather than per-tag-per-guest.
        unique_tags = {tag_name for guest in guests for tag_name in _valid_names(guest)}
        tag_cache = {tag_name: ensure_tag(tag_name, VirtualMachine) for tag_name in unique_tags}
        for guest in guests:
            name = str(guest.get("name") or "")
            tag_objs = [tag_cache[tag_name] for tag_name in _valid_names(guest)]
            if not name or not tag_objs:
                continue
            vm = VirtualMachine.objects.filter(name=name).first()
            if vm is None:  # not created (e.g. dry run) — nothing to tag
                continue
            vm.tags.add(*tag_objs)


register_jobs(SeedVirtualization)
