"""Behaviour check for discovered drives and hardware row quantities."""
from __future__ import annotations

from nautobot_hardware_seed import row, run
from nautobot_hardware_seed_fakes import Record


def check_discovered_drives_and_quantity() -> None:
    """Live drive discovery wins placement, and row quantities reconcile copies."""
    device = Record(name="node-a")
    stale = Record(
        asset_tag="SSD-ROW#1",
        parent_module_bay=Record(parent_device=device),
        location=None,
    )
    job, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [
                row("SSD-ROW", category="nVmE 2.5 SATA", installed_in="node-a")
            ],
        },
        [device],
        existing_modules=[stale],
        inventory_items=[Record(device=device, discovered=True, name="Drive SN-device")],
    )
    assert not stores["module"], "a covered device must not keep a table-owned drive Module"
    assert not stores["module_bay"], "the covered drive row must not create a bay"
    assert any(
        "SSD-ROW: table places this drive in node-a, but node-a reports its own drives" in warning
        for warning in job.logger.warnings
    ), job.logger.warnings

    uncovered = Record(name="node-b")
    _, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [
                row("HDD-ROW", category="hDd 3.5 SATA", installed_in="node-b")
            ],
        },
        [uncovered],
        inventory_items=[Record(device=uncovered, discovered=False, name="Drive SN-uncovered")],
    )
    assert len(stores["module"]) == 1, "an uncovered device keeps the existing placement behavior"
    assert stores["module"][0].parent_module_bay.parent_device is uncovered
    assert stores["module"][0].location is None

    _, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [
                row("HDD-PAIR", category="HDD 3.5 SATA", quantity=2, installed_in="node-b")
            ],
        },
        [uncovered],
        inventory_items=[],
    )
    bays = {module.asset_tag: module.parent_module_bay for module in stores["module"]}
    assert set(bays) == {"HDD-PAIR#1", "HDD-PAIR#2"}
    assert bays["HDD-PAIR#1"] is not bays["HDD-PAIR#2"], "a ModuleBay holds one Module"
    assert {bay.name for bay in bays.values()} == {"HDD-PAIR#1", "HDD-PAIR#2"}

    legacy = Record(
        asset_tag="RAM-ROW",
        parent_module_bay=None,
        location=Record(name="spares"),
    )
    _, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [row("RAM-ROW", category="RAM", quantity=2)],
        },
        [],
        existing_modules=[legacy],
    )
    by_tag = {module.asset_tag: module for module in stores["module"]}
    assert set(by_tag) == {"RAM-ROW#1", "RAM-ROW#2"}
    assert by_tag["RAM-ROW#1"] is legacy, "the existing unsuffixed Module must become #1"
    assert legacy.validated_saves == 1
    assert all(module.parent_module_bay is None for module in by_tag.values())
    assert all(module.location.name == "spares" for module in by_tag.values())

    surplus = Record(asset_tag="RAM-DROP#3", parent_module_bay=None, location=None)
    _, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [row("RAM-DROP", category="RAM", quantity=2)],
        },
        [],
        existing_modules=[
            Record(asset_tag="RAM-DROP#1", parent_module_bay=None, location=None),
            Record(asset_tag="RAM-DROP#2", parent_module_bay=None, location=None),
            surplus,
        ],
    )
    assert {module.asset_tag for module in stores["module"]} == {
        "RAM-DROP#1",
        "RAM-DROP#2",
    }
    assert surplus not in stores["module"], "copies above the current quantity must be deleted"

    dry_device = Record(name="node-dry")
    dry_stale = Record(
        asset_tag="SSD-DRY#1",
        parent_module_bay=Record(parent_device=dry_device),
        location=None,
    )
    dry_legacy = Record(
        asset_tag="RAM-DRY",
        parent_module_bay=None,
        location=Record(name="spares"),
    )
    job, stores = run(
        {
            "hardware_devices": [],
            "hardware_modules": [
                row("SSD-DRY", category="SSD 2.5 SATA", quantity=2, installed_in="node-dry"),
                row("RAM-DRY", category="RAM", quantity=2),
            ],
        },
        [dry_device],
        dryrun=True,
        existing_modules=[dry_stale, dry_legacy],
        inventory_items=[Record(device=dry_device, discovered=True, name="Drive SN-dry_device")],
    )
    assert stores["module"] == [dry_stale, dry_legacy]
    assert dry_stale.asset_tag == "SSD-DRY#1"
    assert dry_legacy.asset_tag == "RAM-DRY", "dry-run must not adopt the old tag"
    assert not stores["module_bay"] and not stores["scaffolding"]
    assert any("table places this drive" in warning for warning in job.logger.warnings)
    assert any("Would delete stale row-owned drive Module" in info for info in job.logger.infos)
    assert any("would delete 1 row-owned Modules" in info for info in job.logger.infos)


def main() -> None:
    """Run every assertion."""
    check_discovered_drives_and_quantity()
    print("nautobot_hardware_seed_quantity: OK")


if __name__ == "__main__":
    main()
