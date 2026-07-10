"""Shared helpers and constants for the homelab SSoT seed jobs (issue #138).

Every seed job reads one resolved JSON bundle (``nautobot_seed.json``, assembled
on the Ansible controller from the four hand-maintained sources) and DiffSyncs
its leaf data into Nautobot. The fixed scaffolding that Nautobot 2.x requires as
foreign keys — Status, LocationType, Location, Manufacturer, DeviceType, Role —
is created here idempotently via the ORM (``get_or_create``) rather than through
DiffSync, so the DiffSync models stay simple and never have to model m2m
``content_types``. Nautobot ORM imports are done lazily inside the helpers so the
module is importable in any context.

Live-validation notes (verify at cutover): exact Nautobot 2.x field names on a
few models (``Prefix.type``, ``IPAddress`` mask handling, Role ``content_types``
API) can shift between minor versions; the helpers below target current 2.x.
"""
from __future__ import annotations

import json
import os
from typing import Any

from nautobot_ssot.contrib import NautobotModel

# Names of the shared prerequisite objects, referenced by every seed job.
STATUS_ACTIVE = "Active"
LOCATION_NAME = "homelab"
LOCATION_TYPE = "Site"
MANUFACTURER = "Generic"


class AdditiveNautobotModel(NautobotModel):
    """A NautobotModel whose ``delete`` is a no-op.

    The seed jobs are additive (create/update only): re-running a seed must
    never remove objects that a different seed job, Device Onboarding, or a
    human added — and because each job's target adapter loads the whole table
    for its model, a destructive sync would otherwise delete objects owned by
    another job. Suppressing delete makes every seed job idempotent and safe to
    re-run in any order.
    """

    def delete(self):  # noqa: D102 - see class docstring
        return self

_EMPTY_BUNDLE: dict[str, list] = {
    "vlans": [],
    "prefixes": [],
    "reservations": [],
    "racks": [],
    "devices": [],
    "nodes": [],
}


def seed_path() -> str:
    """Return the resolved seed-bundle path from the environment."""
    root = os.environ.get("NAUTOBOT_ROOT", "/opt/nautobot")
    return os.environ.get("NAUTOBOT_SEED_FILE", os.path.join(root, "nautobot_seed.json"))


def load_seed() -> dict[str, Any]:
    """Load the seed bundle, tolerating a missing file (returns empty arrays)."""
    path = seed_path()
    if not os.path.isfile(path):
        return dict(_EMPTY_BUNDLE)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    merged = dict(_EMPTY_BUNDLE)
    merged.update({key: (data.get(key) or []) for key in _EMPTY_BUNDLE})
    return merged


def _active_status():
    """Return the shipped ``Active`` Status object."""
    from nautobot.extras.models import Status

    return Status.objects.get(name=STATUS_ACTIVE)


def ensure_location():
    """Idempotently ensure the ``Site`` LocationType and ``homelab`` Location exist.

    The LocationType is granted the content types the seed jobs place in it
    (device, rack, prefix, vlan, ip address) so those objects can be located.
    """
    from django.contrib.contenttypes.models import ContentType
    from nautobot.dcim.models import Device, Location, LocationType, Rack
    from nautobot.ipam.models import VLAN, IPAddress, Prefix

    location_type, _ = LocationType.objects.get_or_create(name=LOCATION_TYPE)
    content_types = [
        ContentType.objects.get_for_model(model)
        for model in (Device, Rack, Prefix, VLAN, IPAddress)
    ]
    location_type.content_types.add(*content_types)

    location, _ = Location.objects.get_or_create(
        name=LOCATION_NAME,
        defaults={"location_type": location_type, "status": _active_status()},
    )
    return location


def ensure_manufacturer():
    """Idempotently ensure the ``Generic`` Manufacturer exists."""
    from nautobot.dcim.models import Manufacturer

    manufacturer, _ = Manufacturer.objects.get_or_create(name=MANUFACTURER)
    return manufacturer


def ensure_device_type(model_name: str):
    """Idempotently ensure a DeviceType (by model) under the Generic manufacturer."""
    from nautobot.dcim.models import DeviceType

    device_type, _ = DeviceType.objects.get_or_create(
        model=model_name, manufacturer=ensure_manufacturer()
    )
    return device_type


def ensure_role(name: str, *models) -> None:
    """Idempotently ensure a Role exists and covers the given content-type models."""
    from django.contrib.contenttypes.models import ContentType
    from nautobot.extras.models import Role

    role, _ = Role.objects.get_or_create(name=name)
    if models:
        role.content_types.add(
            *[ContentType.objects.get_for_model(model) for model in models]
        )
