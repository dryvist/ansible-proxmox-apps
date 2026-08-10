"""Nautobot Job: export the inventory to the S3 artifact bucket (issue #138).

Gathers Nautobot's IPAM/DCIM contents via the ORM, shapes them into the
homelab-contracts ``nautobot-export-v1`` document, validates against that
schema when present, and uploads the JSON to the S3 state bucket with ambient
credentials — mirroring ``terraform-proxmox/inventory_publish.tf`` so every
consumer reads the artifact, never live Nautobot, and a full rebuild works with
Nautobot down.

``build_export()`` is the single place the output is shaped, so aligning field
names with the finalized schema is a one-function change.

The export runs after an ingest, not on a clock. ``_assert_ingest_ordering()``
enforces that; see its docstring for why a scheduled export is what broke here.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import boto3
from nautobot.apps.jobs import Job, register_jobs
from nautobot.dcim.models import Device, Interface, Rack
from nautobot.extras.models import JobResult
from nautobot.ipam.models import VLAN, IPAddress, Prefix
from nautobot.virtualization.models import VirtualMachine

SCHEMA_VERSION = "1.1.0"
DEFAULT_KEY = "nautobot/nautobot_export.json"

# Ingest jobs that write the content this export publishes, identified by
# MODULE NAME. Any one succeeding counts as "an ingest happened" — they are
# separate jobs only because they cover separate domains, and a run touching
# one domain is still a real change worth publishing.
#
# Matched via job_model, NOT via JobResult.name. Nautobot writes two different
# forms into that field for the same job — the Job's Meta name, and
# "module.ClassName" — depending on how the run was started. A name= filter
# therefore matches only some of a job's own results, which would freeze the
# "last export" timestamp and leave this guard passing unconditionally while
# reporting nothing wrong. Silent degradation is the failure mode the guard
# exists to prevent, so it must not be built on that field. job_model is a
# foreign key to the Job record and survives a Meta name change.
INGEST_JOB_MODULES = (
    "ssot_virtualization",
    "ssot_nodes",
    "ssot_vlans_prefixes",
    "ssot_ip_addresses",
    "ssot_dcim",
    "ssot_hardware",
)

# This job's own module, used to find the previous export. Derived from
# __name__ so renaming the file cannot silently desynchronize it.
EXPORT_JOB_MODULE = __name__.rsplit(".", 1)[-1]

# Models whose rows make up the export. Their newest last_updated is the
# document's `data_as_of`.
SOURCE_MODELS = (VLAN, Prefix, IPAddress, Device, Rack, Interface, VirtualMachine)

# Custom-field key holding the Proxmox guest id. Written by the virtualization
# seed job (ssot_virtualization.py); read here.
VMID_FIELD = "vmid"


def _name(obj: Any, attr: str) -> Optional[str]:
    """Return ``obj.<attr>.name`` when the related object is set, else None."""
    related = getattr(obj, attr, None)
    return related.name if related is not None else None


def _all(related: Any) -> list[Any]:
    """Return a concrete list from a Django related manager or plain iterable."""
    if related is None:
        return []
    if hasattr(related, "all"):
        return list(related.all())
    return list(related)


def _address(value: Any, *, host_only: bool = False) -> Optional[str]:
    """Return a string IP address, optionally without its prefix length."""
    if value is None:
        return None
    rendered = str(getattr(value, "address", value))
    if host_only:
        return rendered.split("/", 1)[0]
    return rendered


def _interface_for_ip(ip: Any) -> Optional[Any]:
    """Find the first interface assigned to a Nautobot IPAddress."""
    for attr in ("interfaces", "assigned_object", "interface"):
        candidate = getattr(ip, attr, None)
        if candidate is None:
            continue
        if attr == "interfaces":
            interfaces = _all(candidate)
            if interfaces:
                return interfaces[0]
            continue
        if getattr(candidate, "device", None) is not None:
            return candidate
    return None


def _assigned_interface(ip: Any) -> Optional[dict]:
    """Return the contract's assigned_interface object for an IPAddress."""
    interface = _interface_for_ip(ip)
    if interface is None:
        return None
    return {"device": interface.device.name, "name": interface.name}


def _interface_mac(interface: Any) -> Optional[str]:
    """Return an interface MAC address as a string when present."""
    mac = getattr(interface, "mac_address", None)
    return str(mac) if mac else None


def _bmc_for_device(device: Any) -> Optional[dict]:
    """Return the contract's BMC object from a device's management interface."""
    for interface in _all(getattr(device, "interfaces", None)):
        if not (
            getattr(interface, "mgmt_only", False)
            or str(getattr(interface, "name", "")).lower() in {"bmc", "idrac", "ipmi"}
        ):
            continue
        addresses = _all(getattr(interface, "ip_addresses", None))
        if not addresses:
            continue
        return {
            "address": _address(addresses[0], host_only=True),
            "mac": _interface_mac(interface),
        }
    return None


def _vmid(vm: Any) -> Optional[int]:
    """Return the guest's Proxmox vmid from its custom-field data, else None.

    Tolerates a missing field, a null, or a non-numeric value — the export must
    never fail because one guest predates the custom field.
    """
    data = getattr(vm, "custom_field_data", None) or {}
    raw = data.get(VMID_FIELD)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _vm_mac(vm: Any) -> Optional[str]:
    """Return the MAC of the guest's first VM interface that carries one."""
    for interface in _all(getattr(vm, "interfaces", None)):
        mac = _interface_mac(interface)
        if mac:
            return mac
    return None


def build_export() -> dict:
    """Shape Nautobot's current contents into the export document.

    Single source of truth for the artifact's field names — adjust here to track
    the homelab-contracts schema.
    """
    vlans = [
        {"vid": v.vid, "name": v.name, "group": _name(v, "vlan_group") or _name(v, "group")}
        for v in VLAN.objects.all()
    ]
    prefixes = [
        {
            "cidr": str(p.prefix),
            "vlan": p.vlan.vid if p.vlan_id else None,
            "role": _name(p, "role"),
        }
        for p in Prefix.objects.all()
    ]
    ip_addresses = [
        {
            "address": _address(getattr(ip, "address", getattr(ip, "host", None))),
            "dns_name": ip.dns_name or None,
            "mac": _interface_mac(_interface_for_ip(ip)),
            "assigned_interface": _assigned_interface(ip),
            "type": getattr(ip, "type", None) or None,
        }
        for ip in IPAddress.objects.all()
    ]
    devices = [
        {
            "name": d.name,
            "role": _name(d, "role"),
            "rack": _name(d, "rack"),
            "bmc": _bmc_for_device(d),
        }
        for d in Device.objects.all()
    ]
    racks = [
        {"name": r.name, "site": _name(r, "location") or ""}
        for r in Rack.objects.all()
    ]
    interfaces = [
        {
            "name": i.name,
            "device": i.device.name,
            "mac": str(i.mac_address) if i.mac_address else None,
            "mgmt_only": i.mgmt_only,
        }
        for i in Interface.objects.all()
    ]

    virtual_machines = [
        {
            "name": vm.name,
            "vmid": _vmid(vm),
            "cluster": _name(vm, "cluster"),
            "role": _name(vm, "role"),
            "tags": sorted(tag.name for tag in _all(getattr(vm, "tags", None))),
            "primary_address": _address(getattr(vm, "primary_ip4", None)),
            "mac": _vm_mac(vm),
        }
        for vm in VirtualMachine.objects.all()
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "vlans": vlans,
        "prefixes": prefixes,
        "ip_addresses": ip_addresses,
        "devices": devices,
        "racks": racks,
        "interfaces": interfaces,
        "virtual_machines": virtual_machines,
    }


class ExportNautobotToS3(Job):
    """Export the Nautobot inventory artifact to S3."""

    class Meta:
        """Job metadata."""

        name = "Export Nautobot Inventory to S3"
        description = "Publish the nautobot-export-v1 artifact to the S3 state bucket."
        has_sensitive_variables = False

    def _assert_ingest_ordering(self) -> None:
        """Refuse to publish when no ingest has succeeded since the last export.

        The export publishes whatever the ingest jobs last wrote. Run it on its
        own and it will happily republish content of any age, succeeding every
        time — so its green result carries no information about whether the
        artifact is current. This guard supplies that missing meaning.

        WHY IT READS JOB RESULTS. Freshness itself must come from the data's own
        timestamps; "a job ran" never proves "the data is current". This guard
        does not make that inference. It uses job history in the *negative*
        direction only: if no ingest has succeeded since the last export, then
        nothing new can have arrived, so there is nothing to publish. Absence of
        an ingest proving staleness is sound and needs no clock. Presence of a
        run proving freshness is the unsound direction, and is not used here.

        WHY NOT COMPARE THE DATA TIMESTAMPS INSTEAD. The trigger is an upstream
        apply completing, which fires whether or not that apply changed
        anything. Comparing max(last_updated) alone would therefore refuse on
        every no-change apply, and a guard that cries wolf gets loosened until
        it is gone. Ordering is what is actually being asserted, so ordering is
        what is checked. The data timestamp is still logged, so a detector can
        watch the one case ordering cannot see: an ingest that reports success
        while syncing nothing.

        There is deliberately no bypass flag. A skipped export costs one run; a
        published stale artifact silently misinforms every consumer of it.
        """
        last_export = (
            JobResult.objects.filter(
                job_model__module_name=EXPORT_JOB_MODULE, status="SUCCESS"
            )
            .order_by("-date_done")
            .values_list("date_done", flat=True)
            .first()
        )
        if last_export is None:
            # First export on this instance. There is no prior publish to be
            # newer than, so ordering cannot be violated yet.
            self.logger.info("No prior successful export — ordering guard passes by default")
            return

        last_ingest = (
            JobResult.objects.filter(
                job_model__module_name__in=INGEST_JOB_MODULES, status="SUCCESS"
            )
            .order_by("-date_done")
            .values_list("date_done", flat=True)
            .first()
        )
        if last_ingest is not None and last_ingest > last_export:
            self.logger.info(
                "Ordering guard passes: ingest succeeded %s, after the last export at %s",
                last_ingest,
                last_export,
            )
            return

        raise RuntimeError(
            "Refusing to publish: no ingest job has succeeded since the last export "
            f"(last export {last_export}, last ingest {last_ingest or 'never'}). "
            "The export is meant to run after an ingest, triggered by the upstream "
            "apply — not on a schedule. Re-run an ingest job first. Do not work "
            "around this by scheduling the export."
        )

    def _data_as_of(self) -> Optional[str]:
        """Return the newest ``last_updated`` across every exported model.

        This is the honest freshness signal — taken from the rows themselves,
        not from any job's history. It is published in the document and logged
        so a detector can alarm on an ingest that succeeds while syncing
        nothing, which the ordering guard cannot see.
        """
        newest = None
        for model in SOURCE_MODELS:
            value = (
                model.objects.order_by("-last_updated")
                .values_list("last_updated", flat=True)
                .first()
            )
            if value is not None and (newest is None or value > newest):
                newest = value
        return newest.isoformat() if newest is not None else None

    def _validate(self, document: dict) -> None:
        """Validate against the homelab-contracts schema when it is present."""
        schema_path = os.environ.get("NAUTOBOT_EXPORT_SCHEMA", "")
        if not schema_path or not os.path.isfile(schema_path):
            self.logger.warning(
                "Export schema %s not found — skipping validation", schema_path or "(unset)"
            )
            return
        import jsonschema  # local import: only needed on the validation path

        with open(schema_path, encoding="utf-8") as handle:
            schema = json.load(handle)
        jsonschema.validate(instance=document, schema=schema)
        self.logger.info("Export validated against %s", schema_path)

    def _upload(self, document: dict) -> None:
        """Upload the document to S3 (ambient creds, optional custom endpoint).

        When a non-AWS endpoint is configured (AWS_ENDPOINT_URL_S3, e.g. an
        on-prem RustFS store), force path-style addressing — such stores
        do not serve the virtual-hosted ``<bucket>.<host>`` form boto3 defaults
        to. A default region keeps the SigV4 signer happy when none is set.
        """
        bucket = os.environ.get("NAUTOBOT_EXPORT_S3_BUCKET", "")
        if not bucket:
            raise ValueError("NAUTOBOT_EXPORT_S3_BUCKET is not set — cannot publish export")
        key = os.environ.get("NAUTOBOT_EXPORT_S3_KEY", DEFAULT_KEY)
        body = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
        client_kwargs: dict[str, Any] = {
            "region_name": os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        }
        if os.environ.get("AWS_ENDPOINT_URL_S3"):
            from botocore.config import Config

            client_kwargs["config"] = Config(s3={"addressing_style": "path"})
        boto3.client("s3", **client_kwargs).put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
        self.logger.info("Published %d bytes to s3://%s/%s", len(body), bucket, key)

    def run(self) -> None:  # noqa: D102 - Nautobot Job entrypoint
        # Ordering first: a stale run must cost nothing and touch nothing.
        self._assert_ingest_ordering()
        document = build_export()
        # Logged, deliberately NOT added to the document. nautobot-export-v1
        # sets "additionalProperties": false at the root and lists every
        # producer field in "required", so a new key fails validation and takes
        # the export down. Putting data_as_of in the artifact is a contract
        # change — a 1.2.0 bump here and in homelab-contracts upstream — and
        # belongs in its own PR. The log line is enough for a detector to watch.
        self.logger.info("Data as of %s", self._data_as_of() or "(no rows)")
        self.logger.info(
            "Built export: %d vlans, %d prefixes, %d ip_addresses, %d devices, "
            "%d racks, %d interfaces, %d virtual_machines",
            len(document["vlans"]),
            len(document["prefixes"]),
            len(document["ip_addresses"]),
            len(document["devices"]),
            len(document["racks"]),
            len(document["interfaces"]),
            len(document["virtual_machines"]),
        )
        self._validate(document)
        self._upload(document)


register_jobs(ExportNautobotToS3)
