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
from datetime import datetime, timezone
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


def build_export() -> dict:
    """Shape Nautobot's current contents into the export document.

    Single source of truth for the artifact's field names — adjust here to track
    the homelab-contracts schema.
    """
    vlans = [
        {"vid": v.vid, "name": v.name, "status": _name(v, "status")}
        for v in VLAN.objects.all()
    ]
    prefixes = [
        {
            "prefix": str(p.prefix),
            "vlan_vid": p.vlan.vid if p.vlan_id else None,
            "role": _name(p, "role"),
            "status": _name(p, "status"),
        }
        for p in Prefix.objects.all()
    ]
    reservations = [
        {
            "address": ip.host,
            "dns_name": ip.dns_name or None,
            "device": None,
            "interface": None,
            "status": _name(ip, "status"),
        }
        for ip in IPAddress.objects.all()
    ]
    devices = [
        {
            "name": d.name,
            "role": _name(d, "role"),
            "status": _name(d, "status"),
            "rack": _name(d, "rack"),
            "position": d.position,
            "primary_ip": str(d.primary_ip.address) if d.primary_ip else None,
            "manufacturer": d.device_type.manufacturer.name,
            "model": d.device_type.model,
            "serial": d.serial or None,
        }
        for d in Device.objects.all()
    ]
    racks = [
        {"name": r.name, "site": _name(r, "location"), "u_height": r.u_height}
        for r in Rack.objects.all()
    ]
    interfaces = [
        {
            "device": i.device.name,
            "name": i.name,
            "mac": str(i.mac_address) if i.mac_address else None,
            "type": i.type,
            "mgmt_only": i.mgmt_only,
        }
        for i in Interface.objects.all()
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "nautobot",
        "vlans": vlans,
        "prefixes": prefixes,
        "reservations": reservations,
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
            "Built export: %d vlans, %d prefixes, %d reservations, %d devices, "
            "%d racks, %d interfaces",
            len(document["vlans"]),
            len(document["prefixes"]),
            len(document["reservations"]),
            len(document["devices"]),
            len(document["racks"]),
            len(document["interfaces"]),
        )
        self._validate(document)
        self._upload(document)


register_jobs(ExportNautobotToS3)
