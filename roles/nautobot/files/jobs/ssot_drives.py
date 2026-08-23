"""SSoT job: physical drives, discovered from the Proxmox API.

Source of truth: the live hypervisors, via ``GET /nodes/{node}/disks/list``.
Target: ``InventoryItem`` with ``discovered=True``, parented to the node's
Device — the model the wider ecosystem already uses for agent-populated
hardware (``netbox-agent`` writes exactly this shape), so anything else that
learns to populate it interoperates instead of colliding.

WHERE A DRIVE LIVES, so that it lives in exactly one place
----------------------------------------------------------
The boundary is an objective fact, not a preference:

* **In a machine** -> the machine is the source, and the drive is an
  ``InventoryItem`` on that Device. Discovered here, every run.
* **On a shelf** -> nothing can discover it, so the hardware tables are the
  source and it stays a ``Module`` with a ``location`` and no
  ``parent_module_bay`` (Nautobot's native parts-bin, see ``ssot_hardware``).

A drive crossing that boundary changes home, which is correct: it stopped being
a spare part and became a component of a device. What must NOT persist is the
model-level drive rows in ``hardware_modules`` (``HDD-HGST-6TB``, quantity 3) —
those describe the same physical drives this job discovers individually, and
leaving both is two records for one drive. Retiring them is a separate,
deliberate change; this job does not delete another job's objects.

WHY THE PROXMOX API AND NOT lsblk OVER SSH
------------------------------------------
The API returns ``serial``, ``vendor``, ``model``, ``size``, ``wwn``, ``type``
(nvme/ssd/hdd/usb) and ``used`` as first-class fields. A hand-rolled lsblk
parser has to re-derive the last two and gets them wrong in ways that look
right: NVMe partitions are ``nvme0n1p3`` so digit-stripping yields ``nvme0n1p``
and every NVMe silently reads as "not in a pool"; a BMC's virtual media
enumerates as a real disk with a model and a shared serial; removable media is
indistinguishable without the removable flag. None of those failure modes exist
here, because the API answers the question directly.

THE ONE FIELD THE API GETS WRONG — and it is SAS, not the controller
--------------------------------------------------------------------
For **SAS** drives, ``/disks/list`` reports the WWN in the ``serial`` field.
Verified live: six SAS drives all returned ``serial == wwn`` while their labels
read ``W471Z6P2`` and friends, and ``/disks/smart`` returns SCSI free text with
no serial in it either. So the API cannot supply a SAS vendor serial at all.

This is NOT a misconfigured controller, and it is worth stating because the
symptom mimics one. The same host's HBA is in full passthrough: ``smartctl -i``
with no ``-d megaraid`` returns ``Serial number: W471Z6P2``, SMART is Available
and Enabled, and the host has zero RAID virtual disks. SATA drives on the very
same controller report a real serial and a *different* WWN. The discriminator
is the transport, not the card.

Writing the WWN into ``serial`` would put a fabricated identity on a device
forever, indistinguishable from a real one. So when serial and WWN agree, this
job records **no serial** and says why in the description; the WWN is kept
regardless, because it is a true stable identifier and it is the name the ZFS
pool references (``scsi-3<wwn>``).

Follow-up, deliberately not solved here: the vendor serial IS obtainable from
the host via ``smartctl``. Reaching it would mean giving this job SSH to the
hypervisors, which is a much larger trust change than an API token, so it wants
its own decision rather than being smuggled in.
"""
from __future__ import annotations

import os
from typing import Optional

from diffsync import Adapter
from nautobot.apps.jobs import register_jobs
from nautobot.dcim.models import Device, InventoryItem
from nautobot_ssot.contrib import NautobotAdapter, NautobotModel
from nautobot_ssot.jobs.base import DataSource

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
        """Only drives this job discovered — never a human's or another job's."""
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


class DrivesProxmoxAdapter(Adapter):
    """Loads drives from the live Proxmox API."""

    top_level = ("drive",)
    drive = DriveInventoryItem

    def __init__(self, *args, job, client, nodes, **kwargs):
        """Store the API client and the node list to sweep."""
        super().__init__(*args, **kwargs)
        self.job = job
        self.client = client
        self.nodes = nodes

    def load(self) -> None:
        """Sweep every node, skipping ones Nautobot does not know as a Device."""
        for node in self.nodes:
            if not Device.objects.filter(name=node).exists():
                # Never invent the parent: an InventoryItem needs a Device, and
                # a placeholder would be indistinguishable from a real node.
                self.job.logger.warning(
                    "Node %r has no Device in Nautobot — its drives are not synced.", node
                )
                continue

            for disk in self.client.disks(node):
                self._load_disk(node, disk)

    def _load_disk(self, node: str, disk: dict) -> None:
        api_serial = str(disk.get("serial") or "").strip()
        wwn = str(disk.get("wwn") or "").strip()
        model = str(disk.get("model") or "").strip().replace("_", " ")
        vendor = str(disk.get("vendor") or "").strip()
        devpath = str(disk.get("devpath") or "")
        media = str(disk.get("type") or _UNKNOWN)
        used = str(disk.get("used") or "")

        # Removable media enumerates as a serial-bearing disk. It is not estate
        # storage, and because this adapter deletes what it no longer sees, a
        # USB stick left plugged in would otherwise churn the inventory.
        if media == "usb":
            return

        # See the module docstring: a serial that merely repeats the WWN is the
        # HBA failing to read one, not a serial.
        serial = "" if _same_identifier(api_serial, wwn) else api_serial
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
            description += " — controller reports the WWN in place of a serial"
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
    to begin with 3 — ``372IK3DGFE1C`` is a live example on this estate.
    """
    if not serial or not wwn:
        return False
    return serial.lower().removeprefix("0x") == wwn.lower().removeprefix("0x")


def _vendor_from_model(model: str) -> Optional[str]:
    """Best-effort manufacturer when the API does not report a vendor."""
    if not model:
        return None
    first = model.split()[0].split("_")[0]
    return first.title() if first.isalpha() else None


class ProxmoxDiskClient:
    """Minimal Proxmox API client — only the disk-list endpoint."""

    def __init__(self, base_url: str, token_id: str, token_secret: str, verify: bool):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        self.verify = verify

    def disks(self, node: str) -> list[dict]:
        """Return the node's disk list, or raise."""
        import requests  # local: keeps import cost off every job registration

        response = requests.get(
            f"{self.base_url}/api2/json/nodes/{node}/disks/list",
            headers=self.headers,
            verify=self.verify,
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("data") or []


class SyncDrivesFromProxmox(DataSource):
    """Discover physical drives from the Proxmox API into Nautobot."""

    class Meta:
        """Job metadata."""

        name = "Sync Drive Inventory from Proxmox"
        description = "Discover physical drives and their serials from the live nodes."
        has_sensitive_variables = False

    def load_source_adapter(self) -> None:
        """Build the API client from the environment and sweep the nodes."""
        base_url = os.environ.get("PROXMOX_API_URL", "").strip()
        token_id = os.environ.get("PROXMOX_TOKEN_ID", "").strip()
        token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "").strip()
        nodes = [n for n in os.environ.get("PROXMOX_NODES", "").split(",") if n.strip()]

        # Fail loudly. A job that finds no credentials and syncs an empty source
        # against a delete-capable target would remove every drive in Nautobot.
        missing = [
            name
            for name, value in (
                ("PROXMOX_API_URL", base_url),
                ("PROXMOX_TOKEN_ID", token_id),
                ("PROXMOX_TOKEN_SECRET", token_secret),
                ("PROXMOX_NODES", nodes),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                "Drive discovery is not configured: missing "
                + ", ".join(missing)
                + ". Refusing to run — an empty source would delete the existing inventory."
            )

        ensure_manufacturer("Generic")
        self.source_adapter = DrivesProxmoxAdapter(
            job=self,
            client=ProxmoxDiskClient(
                base_url,
                token_id,
                token_secret,
                verify=os.environ.get("PROXMOX_VERIFY_TLS", "true").lower() != "false",
            ),
            nodes=[n.strip() for n in nodes],
        )
        self.source_adapter.load()

    def load_target_adapter(self) -> None:
        """Load the drives Nautobot already has."""
        self.target_adapter = DrivesNautobotAdapter(job=self)
        self.target_adapter.load()


register_jobs(SyncDrivesFromProxmox)
