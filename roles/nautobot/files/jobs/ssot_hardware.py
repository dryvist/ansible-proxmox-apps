"""Seed job: the physical hardware inventory (Devices and Modules).

Source of truth: the ``hardware_devices`` and ``hardware_modules`` arrays of the
seed bundle, rendered upstream from the hardware inventory tables.

Why this is a plain Job and not a DiffSync DataSource like its siblings:
``Module`` and ``ModuleBay`` both declare ``natural_key_field_names = ["pk"]``,
because their parentage is recursive. ``nautobot_ssot``'s contrib models resolve
every foreign key through the related object's natural key, so a DiffSync
attribute for ``parent_module_bay`` would have to carry a primary key — a value
that is not stable across environments and is not in the source data. An
idempotent ORM upsert keyed on the unique ``asset_tag`` expresses the same
additive contract without that problem.

Additive, exactly like the DiffSync seeds: nothing here deletes. An object that
disappears from the source is left alone, because a second job, Device
Onboarding, or a human may own it.

Spares are the point. An uninstalled component is a ``Module`` with a
``location`` and no ``parent_module_bay`` — those two are mutually exclusive by
model constraint, and that is Nautobot's native parts-bin representation.
``InventoryItem`` is NOT used: it requires a parent Device, so it cannot
represent a part that is sitting on a shelf, which is the majority of this data.
"""
from __future__ import annotations

from nautobot.apps.jobs import BooleanVar, Job, register_jobs

from ssot_common import (
    ensure_device_type,
    ensure_location,
    ensure_module_type,
    ensure_role,
    ensure_status,
    ensure_sublocation,
    load_seed,
)

HARDWARE_ROLE = "hardware"


def _module_bay(device, name: str):
    """Idempotently return the named ModuleBay on a Device."""
    from nautobot.dcim.models import ModuleBay

    bay, _ = ModuleBay.objects.get_or_create(parent_device=device, name=name)
    return bay


class SeedHardware(Job):
    """Upsert the hardware inventory's Devices and Modules."""

    dryrun = BooleanVar(
        default=False,
        description="Report what would change without writing anything.",
    )

    class Meta:
        """Job metadata."""

        name = "Seed Hardware Inventory"
        description = "Upsert Devices and Modules (including spares) from the seed bundle."
        has_sensitive_variables = False

    def run(self, *, dryrun=False):  # noqa: D102 - see class docstring
        from nautobot.dcim.models import Device, Module

        seed = load_seed()
        devices = seed["hardware_devices"]
        modules = seed["hardware_modules"]

        if not devices and not modules:
            self.logger.warning(
                "The seed bundle carries no hardware slice. Nothing was changed. "
                "Set INT_HOMELAB_HARDWARE on the controller if this is unexpected."
            )
            return "no hardware slice in the seed bundle"

        ensure_location()
        ensure_role(HARDWARE_ROLE, Device, Module)

        created = updated = skipped = 0

        for row in devices:
            # A row whose Location names a host is that host — the rack-server
            # slice already owns that Device, with its service tag and BMC.
            # Claiming the name here would be a second writer for one object.
            if row.get("installed_in"):
                skipped += 1
                self.logger.info(
                    "%s describes the chassis %r, which the rack-server seed owns — left alone.",
                    row["hw_id"],
                    row["installed_in"],
                )
                continue

            location = ensure_sublocation(row["location"])
            device_type = ensure_device_type(row["model"] or row["hw_id"], row["manufacturer"])
            defaults = {
                "device_type": device_type,
                "role": ensure_role(HARDWARE_ROLE, Device),
                "location": location,
                "status": ensure_status(row["status"], Device),
                "asset_tag": row["hw_id"],
            }
            if dryrun:
                exists = Device.objects.filter(name=row["hw_id"]).exists()
                created, updated = (created, updated + 1) if exists else (created + 1, updated)
                continue
            _, was_created = Device.objects.update_or_create(
                name=row["hw_id"], defaults=defaults
            )
            created, updated = (created + 1, updated) if was_created else (created, updated + 1)

        for row in modules:
            module_type = ensure_module_type(
                row["model"] or row["hw_id"], row["manufacturer"], row["part_number"]
            )
            defaults = {
                "module_type": module_type,
                "status": ensure_status(row["status"], Module),
            }

            parent = row.get("installed_in")
            device = Device.objects.filter(name=parent).first() if parent else None
            if parent and device is None:
                # Never invent a chassis to hang this on: a placeholder Device
                # would be indistinguishable from a real one forever after. Put
                # it in its stated location and say so.
                self.logger.warning(
                    "%s says it is installed in %r, but no such Device exists. "
                    "Filed at location %r instead.",
                    row["hw_id"],
                    parent,
                    row["location"],
                )
            if device is not None:
                defaults["parent_module_bay"] = _module_bay(device, row["hw_id"])
                defaults["location"] = None  # mutually exclusive by model constraint
            else:
                defaults["parent_module_bay"] = None
                defaults["location"] = ensure_sublocation(row["location"])

            if dryrun:
                exists = Module.objects.filter(asset_tag=row["hw_id"]).exists()
                created, updated = (created, updated + 1) if exists else (created + 1, updated)
                continue
            _, was_created = Module.objects.update_or_create(
                asset_tag=row["hw_id"], defaults=defaults
            )
            created, updated = (created + 1, updated) if was_created else (created, updated + 1)

        verb = "would create/update" if dryrun else "created/updated"
        summary = (
            f"{verb} {created} new and {updated} existing objects "
            f"from {len(devices)} device and {len(modules)} module rows "
            f"({skipped} chassis rows left to the rack-server seed)"
        )
        self.logger.info(summary)
        return summary


register_jobs(SeedHardware)
