"""SSoT job: physical drives, from the seed bundle.

Source of truth: the live hypervisors, read there by ansible-proxmox's
``pve_disk_inventory`` role and carried here in the ``drives`` slice of the seed
bundle. Target: ``InventoryItem`` with ``discovered=True``, parented to the
node's Device — the model the wider ecosystem already uses for agent-populated
hardware (``netbox-agent`` writes exactly this shape), so anything else that
learns to populate it interoperates instead of colliding.

WHY THE BUNDLE AND NOT THE PROXMOX API DIRECTLY
-----------------------------------------------
An earlier revision of this job called ``/nodes/{node}/disks/list`` itself. The
data is identical either way — the gathering role calls that same endpoint — but
doing it from here required a Proxmox API credential that does not exist, for a
job that only ever reads. That meant minting a second Proxmox token and opening a
path from an application guest to the hypervisor API, both purely to list disks.

The gathering repo already holds SSH certificate access to every node, so it runs
``pvesh`` locally as root and needs no token at all, and the bundle is the route
this database already ingests every other fact through. **Zero new credentials,
zero new network paths.** Only the source adapter changed; the model, the diff
semantics and the ownership boundary below are unchanged.

WHERE A DRIVE LIVES, so that it lives in exactly one place
----------------------------------------------------------
The boundary is an objective fact, not a preference:

* **In a machine** -> the machine is the source, and the drive is an
  ``InventoryItem`` on that Device. Recorded here, every run.
* **On a shelf** -> nothing can discover it, so the hardware tables are the
  source and it stays a ``Module`` with a ``location`` and no
  ``parent_module_bay`` (Nautobot's native parts-bin, see ``ssot_hardware``).

A drive crossing that boundary changes home, which is correct: it stopped being
a spare part and became a component of a device. What must NOT persist is the
model-level drive rows in ``hardware_modules`` (``HDD-HGST-6TB``, quantity 3) —
those describe the same physical drives this job records individually, and
leaving both is two records for one drive. Retiring them is a separate,
deliberate change; this job does not delete another job's objects.

THE ONE FIELD THE SOURCE GETS WRONG — and it is SAS, not the controller
-----------------------------------------------------------------------
For **SAS** drives, the Proxmox disk list reports the WWN in the ``serial``
field. Verified live: six SAS drives all returned ``serial == wwn`` while their
labels read otherwise, and the SMART endpoint returns SCSI free text with no
serial in it either. So the source cannot supply a SAS vendor serial at all.

This is NOT a misconfigured controller, and it is worth stating because the
symptom mimics one. The same host's HBA is in full passthrough: ``smartctl -i``
with no ``-d megaraid`` returns the real vendor serial, SMART is Available and
Enabled, and the host has zero RAID virtual disks. SATA drives on the very same
controller report a real serial and a *different* WWN. The discriminator is the
transport, not the card.

Writing the WWN into ``serial`` would put a fabricated identity on a device
forever, indistinguishable from a real one. So when serial and WWN agree, this
job records **no serial** and says why in the description; the WWN is kept
regardless, because it is a true stable identifier and it is the name the ZFS
pool references (``scsi-3<wwn>``).

Follow-up, deliberately not solved here: the vendor serial IS obtainable on the
host via ``smartctl``. Reading it belongs in the gathering role, not here.
"""
from __future__ import annotations

from typing import Optional

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.dcim.models import Device, InventoryItem
from nautobot_ssot.contrib import NautobotAdapter, NautobotModel
from nautobot_ssot.jobs.base import DataSource

from ssot_common import ensure_manufacturer, load_seed

# Proxmox reports these in `used` for a disk that belongs to a ZFS pool. A boot
# disk reports "BIOS boot" instead even though it carries rpool, so this set is
# "is a pool member", never "is in service" — the description records the raw
# value either way rather than collapsing it.
_ZFS_USED = {"ZFS", "zfs_member"}

# Nautobot's InventoryItem.name is unique per (device, name). devpath is stable
# per boot but NOT across reboots, so it must never be the identifier; the drive
# identity is its serial or, failing that, its WWN.
_UNKNOWN = "unknown"


class DriveInventoryItem(NautobotModel):
    """A discovered physical drive, as an InventoryItem on its node's Device.

    Deletable on purpose, unlike the seed jobs' AdditiveNautobotModel. This job
    owns every object it loads — `get_queryset` scopes the target adapter to
    `discovered=True` items whose name marks them as drives — so a drive that
    has genuinely left a machine SHOULD disappear. An additive-only sync would
    accumulate every disk ever installed and quietly stop being an inventory.
    """

    @classmethod
    def get_queryset(cls):
        """Only drives this job recorded — never a human's or another job's."""
        return InventoryItem.objects.filter(discovered=True, name__startswith="Drive ")

    _model = InventoryItem
    _modelname = "drive"
    _identifiers = ("device__name", "name")
    _attributes = ("manufacturer__name", "part_id", "serial", "description")

    device__name: str
    name: str
    manufacturer__name: Optional[str] = None
    part_id: Optional[str] = None
    serial: Optional[str] = None
    description: Optional[str] = None


class DrivesNautobotAdapter(NautobotAdapter):
    """Loads the drives already recorded in Nautobot."""

    top_level = ("drive",)
    drive = DriveInventoryItem


class DrivesSeedAdapter(Adapter):
    """Loads drives from the seed bundle's ``drives`` slice."""

    top_level = ("drive",)
    drive = DriveInventoryItem

    def __init__(self, *args, job, rows, **kwargs):
        """Store the job (for logging) and the bundle rows to load."""
        super().__init__(*args, **kwargs)
        self.job = job
        self.rows = rows

    def load(self) -> None:
        """Load every row whose node Nautobot knows as a Device."""
        # Cached because the row count runs to dozens per node and the answer
        # cannot change mid-load.
        known: dict[str, bool] = {}
        for row in self.rows:
            node = str(row.get("node") or "").strip()
            if not node:
                self.job.logger.warning(
                    "A drive row carries no node and cannot be attached to a "
                    "Device — skipped (%s).",
                    row.get("devpath") or "no devpath",
                )
                continue
            if node not in known:
                known[node] = Device.objects.filter(name=node).exists()
            if not known[node]:
                # Never invent the parent: an InventoryItem needs a Device, and
                # a placeholder would be indistinguishable from a real node.
                self.job.logger.warning(
                    "Node %r has no Device in Nautobot — its drives are not synced.", node
                )
                continue
            self._load_disk(node, row)

    def _load_disk(self, node: str, disk: dict) -> None:
        reported_serial = str(disk.get("serial") or "").strip()
        wwn = str(disk.get("wwn") or "").strip()
        model = str(disk.get("model") or "").strip().replace("_", " ")
        vendor = str(disk.get("vendor") or "").strip()
        devpath = str(disk.get("devpath") or "")
        media = str(disk.get("type") or _UNKNOWN)
        used = str(disk.get("used") or "")

        # See the module docstring: a serial that merely repeats the WWN is the
        # transport failing to carry one, not a serial.
        serial = "" if _same_identifier(reported_serial, wwn) else reported_serial
        identity = serial or wwn
        if not identity:
            self.job.logger.warning(
                "%s on %s reports neither a serial nor a WWN — skipped, as it "
                "cannot be identified across reboots (%s).",
                devpath,
                node,
                model or "unknown model",
            )
            return

        description = f"{media}, {disk.get('size') or '?'} bytes, used={used or 'free'}"
        if wwn:
            description += f", wwn={wwn}"
        if not serial:
            description += " — the transport reports the WWN in place of a serial"
        if used in _ZFS_USED:
            description += " — ZFS pool member"

        self.add(
            self.drive(
                device__name=node,
                # Namespaced so get_queryset can scope to this job's objects
                # without a tag, and stable across reboots unlike devpath.
                name=f"Drive {identity}",
                manufacturer__name=vendor or _vendor_from_model(model),
                part_id=model or None,
                serial=serial or None,
                description=description[:255],
            )
        )


def _same_identifier(serial: str, wwn: str) -> bool:
    """True when the reported serial is really just the WWN.

    Only the ``0x`` prefix is normalised. An earlier version also stripped a
    leading ``3`` (the SCSI-name prefix in ``scsi-3<wwn>``), which is not part
    of either value here and would silently mangle any real serial that happens
    to begin with 3 — the estate carries a live example.
    """
    if not serial or not wwn:
        return False
    return serial.lower().removeprefix("0x") == wwn.lower().removeprefix("0x")


def _vendor_from_model(model: str) -> Optional[str]:
    """Best-effort manufacturer when the source does not report a vendor."""
    if not model:
        return None
    first = model.split()[0].split("_")[0]
    return first.title() if first.isalpha() else None


class SyncDrivesFromSeed(DataSource):
    """Sync physical drives from the seed bundle into Nautobot."""

    class Meta:
        """Job metadata."""

        name = "Sync Drive Inventory from Proxmox"
        description = "Record physical drives and their serials from the live nodes."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Load the bundle's drive slice, refusing to run on an empty one."""
        rows = load_seed()["drives"]

        # Fail loudly. Every other seed job is additive, so an absent slice
        # simply contributes nothing. This one DELETES what it stops seeing, so
        # the same empty slice would remove every drive in Nautobot. `load_seed`
        # defaults a missing key to [], which makes "the gathering role never
        # ran" and "there are genuinely no drives" indistinguishable — and only
        # one of those should ever reach a delete-capable sync.
        if not rows:
            raise ValueError(
                "The seed bundle carries no `drives` slice. Refusing to run — an "
                "empty source would delete the existing drive inventory. Set "
                "ANSIBLE_PROXMOX_DRIVES on the controller and re-run the "
                "pve_disk_inventory role in ansible-proxmox."
            )

        ensure_manufacturer("Generic")
        self.source_adapter = DrivesSeedAdapter(job=self, rows=rows)
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the drives Nautobot already has."""
        self.target_adapter = DrivesNautobotAdapter(job=self)
        self.target_adapter.load()


register_jobs(SyncDrivesFromSeed)
