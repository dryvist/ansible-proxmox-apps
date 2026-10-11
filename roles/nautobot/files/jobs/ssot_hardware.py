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

An object that disappears from the source is left alone, because a second job,
Device Onboarding, or a human may own it. This job only deletes its own surplus
Modules when a row's quantity drops, or stale drive Modules on a Device whose
own discovered InventoryItems are authoritative.

Spares are the point. An uninstalled component is a ``Module`` with a
``location`` and no ``parent_module_bay`` — those two are mutually exclusive by
model constraint, and that is Nautobot's native parts-bin representation.
``InventoryItem`` is NOT used: it requires a parent Device, so it cannot
represent a part that is sitting on a shelf, which is the majority of this data.
Drives installed in a Device with discovered InventoryItems belong to
``ssot_drives``; this job leaves no row-owned drive Module in that Device's bays.
Rows with quantity greater than one become one Module per unit.
"""
from __future__ import annotations

from nautobot.apps.jobs import BooleanVar, Job, register_jobs

from ssot_common import (
    ensure_device_type,
    ensure_location,
    ensure_module_type,
    ensure_procurement_fields,
    ensure_role,
    ensure_status,
    ensure_sublocation,
    load_seed,
)
from ssot_hardware_fields import (
    _adopt_module_tag,
    _apply_procurement_data,
    _is_drive,
    _module_asset_tags,
    _row_modules,
    _serial,
)

HARDWARE_ROLE = "hardware"





def _upsert_circuits(job, circuits, dryrun: bool) -> tuple[int, int]:
    """Upsert Providers, CircuitTypes and Circuits. Returns (created, updated)."""
    from nautobot.circuits.models import Circuit, CircuitType, Provider

    from ssot_common import ensure_status

    created = updated = 0
    for row in circuits:
        if dryrun:
            exists = Circuit.objects.filter(cid=row["circuit_id"]).exists()
            created, updated = (created, updated + 1) if exists else (created + 1, updated)
            continue

        provider, _ = Provider.objects.get_or_create(name=row["provider"])
        circuit_type, _ = CircuitType.objects.get_or_create(name=row["circuit_type"])
        _, was_created = Circuit.objects.update_or_create(
            cid=row["circuit_id"],
            defaults={
                "provider": provider,
                "circuit_type": circuit_type,
                "status": ensure_status(
                    row["status"], Circuit, logger=job.logger, subject=row["circuit_id"]
                ),
                "description": row.get("description", "")[:200],
            },
        )
        created, updated = (created + 1, updated) if was_created else (created, updated + 1)

    # Terminations are deliberately not created. A CircuitTermination points at
    # a Location or a device Interface, and neither is recorded for these
    # uplinks. Guessing one would put a made-up physical connection into the
    # record, which is worse than an untermined circuit that is honestly
    # incomplete.
    if circuits:
        job.logger.info(
            "Circuits carry no terminations: the source records no interface or "
            "location for them. Add terminations when that data exists."
        )
    return created, updated


def _module_bay(device, name: str):
    """Idempotently return the named ModuleBay on a Device."""
    from nautobot.dcim.models import ModuleBay

    bay, _ = ModuleBay.objects.get_or_create(parent_device=device, name=name)
    return bay


def _cleanup_orphan_bays(hw_id: str, keep_device, logger) -> None:
    """Delete empty ModuleBays named ``hw_id`` on any device other than ``keep_device``.

    ``keep_device=None`` considers every device, for a bay name no unit uses.

    A component that moves between chassis leaves its old ModuleBay behind —
    Nautobot never deletes a bay on its own, and a second bay with this same
    name is purely an orphan from the move (``_module_bay`` always names a bay
    for the hw_id of the part placed in it, never shared). Only bays this job
    itself could have created are considered: ``parent_device`` bays, never a
    bay nested under another Module, which belongs to a different model of
    recursive parentage this job does not manage. A bay still holding a
    Module is left alone — that is a real installation, not an orphan.
    """
    from nautobot.dcim.models import Module, ModuleBay

    orphans = ModuleBay.objects.filter(name=hw_id, parent_device__isnull=False)
    if keep_device is not None:
        orphans = orphans.exclude(parent_device=keep_device)
    for bay in orphans:
        if Module.objects.filter(parent_module_bay=bay).exists():
            continue
        logger.info(
            "Deleting orphan ModuleBay %r on %s — %s is now installed elsewhere.",
            hw_id,
            bay.parent_device,
            hw_id,
        )
        bay.delete()


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
        from nautobot.dcim.models import Device, InventoryItem, Module

        seed = load_seed()
        devices = seed["hardware_devices"]
        modules = seed["hardware_modules"]
        circuits = seed["wan_circuits"]

        if not devices and not modules and not circuits:
            self.logger.warning(
                "The seed bundle carries no hardware slice. Nothing was changed. "
                "Set NAUTOBOT_SEED_HARDWARE on the controller if this is unexpected."
            )
            return "no hardware slice in the seed bundle"

        # Scaffolding writes too — it creates a Role and flips the LocationType
        # to nestable — so it is gated with everything else. A dry run that
        # quietly mutates the schema is not a dry run.
        hardware_role = None
        if not dryrun:
            ensure_location()
            hardware_role = ensure_role(HARDWARE_ROLE, Device, Module)
            ensure_procurement_fields()

        created = updated = deleted = skipped = 0

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

            # Before any ensure_* call: those are get_or_create, so resolving a
            # DeviceType or a Location on the way to "would create" would write.
            if dryrun:
                exists = Device.objects.filter(name=row["hw_id"]).exists()
                created, updated = (created, updated + 1) if exists else (created + 1, updated)
                continue

            defaults = {
                "device_type": ensure_device_type(
                    row["model"] or row["hw_id"], row["manufacturer"]
                ),
                "role": hardware_role,
                "location": ensure_sublocation(row["location"]),
                "status": ensure_status(
                    row["status"], Device, logger=self.logger, subject=row["hw_id"]
                ),
                "asset_tag": row["hw_id"],
                # Absent in the source is NOT "clear what is there": a row that
                # carries no serial must leave an existing one alone, because a
                # discovered serial is better evidence than a hand-written table
                # that omitted it. Only a non-empty value overwrites.
                **({"serial": _serial(row)} if _serial(row) else {}),
            }
            device, was_created = Device.objects.update_or_create(
                name=row["hw_id"], defaults=defaults
            )
            created, updated = (created + 1, updated) if was_created else (created, updated + 1)
            _apply_procurement_data(device, row)

        for row in modules:
            hw_id = row["hw_id"]
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

            owned_modules = _row_modules(Module, hw_id)
            if (
                _is_drive(row)
                and device is not None
                and InventoryItem.objects.filter(device=device, discovered=True).exists()
            ):
                self.logger.warning(
                    "%s: table places this drive in %s, but %s reports its own drives; "
                    "record it at a bin location in the table if it is a spare",
                    hw_id,
                    device.name,
                    device.name,
                )
                for asset_tag, module in owned_modules.items():
                    bay = getattr(module, "parent_module_bay", None)
                    if bay is None or getattr(bay, "parent_device", None) != device:
                        continue
                    action = "Would delete" if dryrun else "Deleting"
                    self.logger.info(
                        "%s stale row-owned drive Module %r from %s.",
                        action,
                        asset_tag,
                        device.name,
                    )
                    if not dryrun:
                        module.delete()
                        bay.delete()
                    deleted += 1
                continue

            asset_tags = _module_asset_tags(hw_id, row.get("quantity"))
            stale_bay_names = (set(owned_modules) | {hw_id, f"{hw_id}#1"}) - set(asset_tags)
            if len(asset_tags) > 1 and f"{hw_id}#1" not in owned_modules and hw_id in owned_modules:
                _adopt_module_tag(owned_modules, hw_id, f"{hw_id}#1", dryrun)
            elif len(asset_tags) == 1 and hw_id not in owned_modules and f"{hw_id}#1" in owned_modules:
                _adopt_module_tag(owned_modules, f"{hw_id}#1", hw_id, dryrun)

            desired_tags = set(asset_tags)
            for asset_tag, module in list(owned_modules.items()):
                if asset_tag in desired_tags:
                    continue
                action = "Would delete" if dryrun else "Deleting"
                self.logger.info(
                    "%s surplus row-owned Module %r after quantity changed to %d.",
                    action,
                    asset_tag,
                    len(asset_tags),
                )
                if not dryrun:
                    module.delete()
                deleted += 1
                del owned_modules[asset_tag]

            if dryrun:
                for asset_tag in asset_tags:
                    if asset_tag in owned_modules:
                        updated += 1
                    else:
                        created += 1
                continue

            defaults = {
                "module_type": ensure_module_type(
                    row["model"] or hw_id, row["manufacturer"], row["part_number"]
                ),
                "status": ensure_status(
                    row["status"], Module, logger=self.logger, subject=hw_id
                ),
                # See the Device loop: omit rather than blank, so a source row
                # without a serial never erases a discovered one.
                **({"serial": _serial(row)} if _serial(row) else {}),
            }
            if device is None:
                defaults["parent_module_bay"] = None
                defaults["location"] = ensure_sublocation(row["location"])

            for asset_tag in asset_tags:
                if device is not None:
                    # One bay per unit: a ModuleBay holds exactly one Module.
                    defaults["parent_module_bay"] = _module_bay(device, asset_tag)
                    defaults["location"] = None  # mutually exclusive by model constraint
                module, was_created = Module.objects.update_or_create(
                    asset_tag=asset_tag, defaults=defaults
                )
                created, updated = (
                    (created + 1, updated)
                    if was_created
                    else (created, updated + 1)
                )
                _apply_procurement_data(module, row)
                if device is not None:
                    _cleanup_orphan_bays(asset_tag, device, self.logger)
            # Bays named for a tag this row no longer uses (quantity changed)
            # are empty orphans on any device, including this one.
            for name in stale_bay_names:
                _cleanup_orphan_bays(name, None, self.logger)

        circuit_created, circuit_updated = _upsert_circuits(self, circuits, dryrun)
        created += circuit_created
        updated += circuit_updated

        verb = "would create/update" if dryrun else "created/updated"
        delete_verb = "would delete" if dryrun else "deleted"
        summary = (
            f"{verb} {created} new and {updated} existing objects; "
            f"{delete_verb} {deleted} row-owned Modules "
            f"from {len(devices)} device, {len(modules)} module and "
            f"{len(circuits)} circuit rows "
            f"({skipped} chassis rows left to the rack-server seed)"
        )
        self.logger.info(summary)
        return summary


register_jobs(SeedHardware)
