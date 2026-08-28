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

from ssot_common import MANUFACTURER as GENERIC_MANUFACTURER
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

# Proxmox reports a LITERAL "unknown" in `vendor` for NVMe, not an empty string,
# so a plain `vendor or fallback` keeps it and Nautobot is then asked for a
# Manufacturer named "unknown" that does not exist. Every create then fails with
# ObjectNotCreated -- and the job still reports SUCCESS, so it reads as a clean
# sync that wrote nothing. Observed: 19 of 19 creates lost exactly this way.
_VENDOR_PLACEHOLDERS = {"", "-", "n/a", "na", "none", "null", "unknown", "?"}


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
    # `discovered` is an ATTRIBUTE, not a side effect: it defaults to False on
    # the model, and get_queryset() above filters on it. Leaving it unset writes
    # rows the target adapter cannot see, so every later run re-creates them and
    # collides on the (device, name) unique constraint — while the rows sit
    # there, invisible, looking like nothing was written at all.
    _attributes = ("manufacturer__name", "part_id", "serial", "description", "discovered")

    device__name: str
    name: str
    # These map to CharFields that are `blank=True` but **NOT NULL**. Passing
    # None raises IntegrityError mid-sync, which aborts the whole run — and it
    # lands on exactly the drives whose serial this job deliberately refuses to
    # fabricate, so the correct-by-design case was the one that broke. Empty
    # string is the model's own "absent", so use it.
    manufacturer__name: Optional[str] = None  # FK: nullable, so None is valid here
    part_id: str = ""
    serial: str = ""
    description: str = ""
    discovered: bool = True


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

        # Resolve the manufacturer to a name that EXISTS. contrib looks the
        # Manufacturer up by name and raises ObjectNotCreated when it is absent,
        # so inventing a name here loses the record.
        manufacturer = _manufacturer_name(vendor, model)
        ensure_manufacturer(manufacturer)

        self.add(
            self.drive(
                device__name=node,
                # Namespaced so get_queryset can scope to this job's objects
                # without a tag, and stable across reboots unlike devpath.
                name=f"Drive {identity}",
                manufacturer__name=manufacturer,
                # Empty string, never None: these columns are NOT NULL.
                part_id=model,
                serial=serial,
                description=description[:255],
                discovered=True,
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


def _manufacturer_name(vendor: str, model: str) -> str:
    """The Manufacturer name to file this drive under. Never a placeholder.

    ``GENERIC_MANUFACTURER`` is the deliberate fallback rather than leaving the
    field empty: contrib resolves ``manufacturer__name`` to a real object, so an
    absent or invented name costs the whole record. "Generic" is honest about
    not knowing, and it already exists.
    """
    if vendor.strip().lower() not in _VENDOR_PLACEHOLDERS:
        return vendor.strip()
    return _vendor_from_model(model) or GENERIC_MANUFACTURER


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

    def post_run(self) -> None:
        """Fail the job when the sync did not actually land the records.

        WHY THIS EXISTS: nautobot_ssot logs a per-object ``[error]`` when a
        create raises and then finishes the job as **SUCCESS** anyway. Observed
        live: all 19 creates failed with ObjectNotCreated, the diff summary
        cheerfully read ``{'create': 19}``, the job reported SUCCESS, and the
        table stayed empty. Nothing in the run said otherwise -- the only way to
        notice was to query the database by hand.

        A sync job whose whole purpose is to persist rows must therefore check
        that the rows are there. Counting is enough: the source is the estate's
        drives, and after a successful sync the target must hold at least as
        many. Fewer means creates were dropped, whatever the status said.
        """
        expected = len(list(self.source_adapter.get_all("drive")))

        # Re-read rather than reuse the pre-sync target adapter, which still
        # holds the old contents and would happily confirm its own staleness.
        actual = DriveInventoryItem.get_queryset().count()

        if actual < expected:
            raise ValueError(
                f"The drive sync reported success but Nautobot holds {actual} "
                f"discovered drives against {expected} from the source. Creates "
                "were dropped -- check the job log for ObjectNotCreated, which "
                "nautobot_ssot records as a per-object error without failing "
                "the job."
            )
        self.logger.info("Verified %s discovered drives are present.", actual)


register_jobs(SyncDrivesFromSeed)
