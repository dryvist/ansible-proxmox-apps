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
    "virtual_machines": [],
    "hardware_devices": [],
    "hardware_modules": [],
    "wan_circuits": [],
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
    from nautobot.dcim.models import Device, Location, LocationType, Module, Rack
    from nautobot.ipam.models import VLAN, IPAddress, Prefix

    location_type, _ = LocationType.objects.get_or_create(name=LOCATION_TYPE)
    # Racks, desks and parts bins are child Locations of `homelab` under this
    # same type, and Nautobot rejects a same-type parent unless the type says
    # it nests. Set it here rather than only in `defaults`, because the type
    # already exists from before spares were modelled.
    if not location_type.nestable:
        location_type.nestable = True
        location_type.validated_save()
    content_types = [
        ContentType.objects.get_for_model(model)
        for model in (Device, Module, Rack, Prefix, VLAN, IPAddress)
    ]
    location_type.content_types.add(*content_types)

    location, _ = Location.objects.get_or_create(
        name=LOCATION_NAME,
        defaults={"location_type": location_type, "status": _active_status()},
    )
    return location


def ensure_manufacturer(name: str = ""):
    """Idempotently ensure a Manufacturer exists, defaulting to ``Generic``."""
    from nautobot.dcim.models import Manufacturer

    manufacturer, _ = Manufacturer.objects.get_or_create(name=name or MANUFACTURER)
    return manufacturer


def ensure_device_type(model_name: str, manufacturer_name: str = ""):
    """Idempotently ensure a DeviceType (by model) under its manufacturer.

    ``manufacturer_name`` defaults to ``Generic``: the original callers had no
    make in their source at all, and (manufacturer, model) is unique, so
    changing the default would strand every DeviceType they already created.
    """
    from nautobot.dcim.models import DeviceType

    device_type, _ = DeviceType.objects.get_or_create(
        model=model_name, manufacturer=ensure_manufacturer(manufacturer_name)
    )
    return device_type


def ensure_module_type(model_name: str, manufacturer_name: str = "", part_number: str = ""):
    """Idempotently ensure a ModuleType (by manufacturer + model).

    ``part_number`` is only applied when creating: a later blank in the source
    must not wipe a number already recorded here.
    """
    from nautobot.dcim.models import ModuleType

    module_type, _ = ModuleType.objects.get_or_create(
        model=model_name,
        manufacturer=ensure_manufacturer(manufacturer_name),
        defaults={"part_number": part_number or ""},
    )
    return module_type


def ensure_role(name: str, *models):
    """Idempotently ensure a Role exists and covers the given content-type models."""
    from django.contrib.contenttypes.models import ContentType
    from nautobot.extras.models import Role

    role, _ = Role.objects.get_or_create(name=name)
    if models:
        role.content_types.add(
            *[ContentType.objects.get_for_model(model) for model in models]
        )
    return role


def ensure_status(name: str, *models, logger=None, subject: str = ""):
    """Return the named Status, granting it the given content types.

    Status is a foreign key on Device and Module, and a shipped Status does not
    automatically apply to every model — it has to carry that content type or
    saving raises. Falls back to ``Active`` for a name Nautobot does not ship,
    so one unexpected source value cannot fail a whole run.

    That fallback is LOUD, and has to be. A typo, a case mismatch or a status
    Nautobot does not ship would otherwise publish a decommissioned or offline
    object as Active, with the run reporting complete success — the exact
    "green run, wrong data" outcome the ingest exists to prevent. Pass
    ``logger`` (and ``subject`` to name the row) from any caller that has one.
    """
    from django.contrib.contenttypes.models import ContentType
    from nautobot.extras.models import Status

    status = Status.objects.filter(name=name).first()
    if status is None:
        status = _active_status()
        if logger is not None:
            logger.warning(
                "%s: status %r is not a Status Nautobot has, so it was recorded "
                "as %s. Correct the source, or add the Status — this object now "
                "reads as live regardless of what the source meant.",
                subject or "hardware row",
                name,
                STATUS_ACTIVE,
            )
    if models:
        status.content_types.add(
            *[ContentType.objects.get_for_model(model) for model in models]
        )
    return status


def ensure_sublocation(name: str):
    """Idempotently ensure a child Location of ``homelab`` (a rack, desk, or bin).

    Spare hardware has to live somewhere Nautobot can express, and a Module's
    ``location`` is the field that holds it. These are real places, so they are
    child Locations rather than tags.
    """
    from nautobot.dcim.models import Location

    parent = ensure_location()
    if not name or name == LOCATION_NAME:
        return parent

    location, _ = Location.objects.get_or_create(
        name=name,
        parent=parent,
        defaults={"location_type": parent.location_type, "status": _active_status()},
    )
    return location


def ensure_tag(name: str, *models):
    """Idempotently ensure a Tag exists and covers the given content-type models.

    Guest tags drive the GraphQL dynamic inventory group construction
    (``inventory/nautobot.yml`` keys its ``*_group`` mapping on ``tags:name``),
    so the seed jobs must import them as first-class Tag objects (issue #1008).
    Mirrors :func:`ensure_role`: additive content-type grants, never removed.
    """
    from django.contrib.contenttypes.models import ContentType
    from nautobot.extras.models import Tag

    tag, _ = Tag.objects.get_or_create(name=name)
    if models:
        tag.content_types.add(
            *[ContentType.objects.get_for_model(model) for model in models]
        )
    return tag
