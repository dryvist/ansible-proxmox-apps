"""Sync Proxmox physical drives to discovered Nautobot InventoryItems.

The job owns only discovered ``Drive *`` items. Because DiffSync can delete
missing rows, the API client validates the full cluster scan before this job
loads any source or target objects.
"""
from __future__ import annotations

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.dcim.models import Device, InventoryItem
from nautobot_ssot.contrib import NautobotAdapter, NautobotModel
from nautobot_ssot.jobs.base import DataSource

from proxmox_disks import ProxmoxDiskClient
from ssot_common import MANUFACTURER as GENERIC_MANUFACTURER
from ssot_common import ensure_manufacturer

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
    manufacturer__name: str | None = None  # FK: nullable, so None is valid here
    part_id: str = ""
    serial: str = ""
    description: str = ""
    discovered: bool = True


class DrivesNautobotAdapter(NautobotAdapter):
    """Loads the drives already recorded in Nautobot."""

    top_level = ("drive",)
    drive = DriveInventoryItem


class DrivesProxmoxAdapter(Adapter):
    """Loads the validated Proxmox drive rows."""

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


def _vendor_from_model(model: str) -> str | None:
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


class SyncDrivesFromProxmox(DataSource):
    """Sync physical drives from the Proxmox API into Nautobot."""

    class Meta:
        """Job metadata."""

        name = "Sync Drive Inventory from Proxmox"
        description = "Record physical drives and their serials from the live nodes."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Validate a complete API scan before loading the source adapter."""
        rows = ProxmoxDiskClient.from_env().rows()
        ensure_manufacturer("Generic")
        self.source_adapter = DrivesProxmoxAdapter(job=self, rows=rows)
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


register_jobs(SyncDrivesFromProxmox)
