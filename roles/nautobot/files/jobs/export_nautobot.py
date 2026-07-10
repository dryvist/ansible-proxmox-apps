"""Nautobot Job: export the inventory to the S3 artifact bucket (issue #138).

Celery-beat scheduled. Gathers Nautobot's IPAM/DCIM contents via the ORM, shapes
them into the homelab-contracts ``nautobot-export-v1`` document, validates
against that schema when present, and uploads the JSON to the S3 state bucket
with ambient credentials — mirroring ``terraform-proxmox/inventory_publish.tf``
so every consumer reads the artifact, never live Nautobot, and a full rebuild
works with Nautobot down.

``build_export()`` is the single place the output is shaped, so aligning field
names with the finalized schema is a one-function change.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import boto3
from nautobot.apps.jobs import Job, register_jobs
from nautobot.dcim.models import Device, Interface, Rack
from nautobot.ipam.models import VLAN, IPAddress, Prefix

SCHEMA_VERSION = "1.0.0"
DEFAULT_KEY = "nautobot/nautobot_export.json"


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

    return {
        "schema_version": SCHEMA_VERSION,
        "vlans": vlans,
        "prefixes": prefixes,
        "ip_addresses": ip_addresses,
        "devices": devices,
        "racks": racks,
        "interfaces": interfaces,
    }


class ExportNautobotToS3(Job):
    """Export the Nautobot inventory artifact to S3."""

    class Meta:
        """Job metadata."""

        name = "Export Nautobot Inventory to S3"
        description = "Publish the nautobot-export-v1 artifact to the S3 state bucket."
        has_sensitive_variables = False

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
        """Upload the document to S3 with ambient credentials."""
        bucket = os.environ.get("NAUTOBOT_EXPORT_S3_BUCKET", "")
        if not bucket:
            raise ValueError("NAUTOBOT_EXPORT_S3_BUCKET is not set — cannot publish export")
        key = os.environ.get("NAUTOBOT_EXPORT_S3_KEY", DEFAULT_KEY)
        body = json.dumps(document, indent=2, sort_keys=True).encode("utf-8")
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
        self.logger.info("Published %d bytes to s3://%s/%s", len(body), bucket, key)

    def run(self) -> None:  # noqa: D102 - Nautobot Job entrypoint
        document = build_export()
        self.logger.info(
            "Built export: %d vlans, %d prefixes, %d ip_addresses, %d devices, "
            "%d racks, %d interfaces",
            len(document["vlans"]),
            len(document["prefixes"]),
            len(document["ip_addresses"]),
            len(document["devices"]),
            len(document["racks"]),
            len(document["interfaces"]),
        )
        self._validate(document)
        self._upload(document)


register_jobs(ExportNautobotToS3)
