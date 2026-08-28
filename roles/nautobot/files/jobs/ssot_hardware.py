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

# Nautobot's `serial` is a plain CharField, so any of None, "", "  " and the
# placeholder dashes people type into markdown tables all have to collapse to
# "no serial known" — otherwise a literal "—" becomes a device's identity and
# looks exactly like a real one forever after.
_SERIAL_PLACEHOLDERS = {
    "",
    "-",
    "--",
    "—",
    "n/a",
    "na",
    "none",
    "unknown",
    "tbd",
    "?",
    # DMI defaults from boards whose serial was never programmed. These are the
    # dangerous ones: unlike "n/a" they LOOK like data, they are identical
    # across every board of that make, and dmidecode returns them confidently.
    # Verified live on this estate's two workstation-class nodes, which report
    # exactly these while the rack servers return real service tags.
    "system serial number",
    "default string",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "not specified",
    "not applicable",
    "0123456789",
    "00000000",
}


def _serial(row) -> str:
    """The row's serial, or "" when it carries nothing usable."""
    value = str(row.get("serial") or "").strip()
    return "" if value.lower() in _SERIAL_PLACEHOLDERS else value


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
        circuits = seed["wan_circuits"]

        if not devices and not modules and not circuits:
            self.logger.warning(
                "The seed bundle carries no hardware slice. Nothing was changed. "
                "Set INT_HOMELAB_HARDWARE on the controller if this is unexpected."
            )
            return "no hardware slice in the seed bundle"

        # Scaffolding writes too — it creates a Role and flips the LocationType
        # to nestable — so it is gated with everything else. A dry run that
        # quietly mutates the schema is not a dry run.
        hardware_role = None
        if not dryrun:
            ensure_location()
            hardware_role = ensure_role(HARDWARE_ROLE, Device, Module)

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
            _, was_created = Device.objects.update_or_create(
                name=row["hw_id"], defaults=defaults
            )
            created, updated = (created + 1, updated) if was_created else (created, updated + 1)

        for row in modules:
            # Same reason as the device loop, and it matters more here:
            # _module_bay() is a get_or_create, so a dry run would leave empty
            # ModuleBays behind on real chassis.
            if dryrun:
                exists = Module.objects.filter(asset_tag=row["hw_id"]).exists()
                created, updated = (created, updated + 1) if exists else (created + 1, updated)
                continue

            defaults = {
                "module_type": ensure_module_type(
                    row["model"] or row["hw_id"], row["manufacturer"], row["part_number"]
                ),
                "status": ensure_status(
                    row["status"], Module, logger=self.logger, subject=row["hw_id"]
                ),
                # See the Device loop: omit rather than blank, so a source row
                # without a serial never erases a discovered one.
                **({"serial": _serial(row)} if _serial(row) else {}),
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

            _, was_created = Module.objects.update_or_create(
                asset_tag=row["hw_id"], defaults=defaults
            )
            created, updated = (created + 1, updated) if was_created else (created, updated + 1)

        circuit_created, circuit_updated = _upsert_circuits(self, circuits, dryrun)
        created += circuit_created
        updated += circuit_updated

        verb = "would create/update" if dryrun else "created/updated"
        summary = (
            f"{verb} {created} new and {updated} existing objects "
            f"from {len(devices)} device, {len(modules)} module and "
            f"{len(circuits)} circuit rows "
            f"({skipped} chassis rows left to the rack-server seed)"
        )
        self.logger.info(summary)
        return summary


register_jobs(SeedHardware)
