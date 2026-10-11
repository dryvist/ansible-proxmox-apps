"""Behaviour check for hardware seed serial field normalization."""
from __future__ import annotations

from nautobot_hardware_seed import load_job, run


def check_dmi_placeholders_are_not_serials() -> None:
    """A firmware default must never become a device's identity.

    These values look like data and can be identical across devices, so writing
    them gives several devices the same "serial" instead of representing it as
    missing data.
    """
    job = load_job()
    serial = job._serial

    for placeholder in (
        "System Serial Number",
        "Default string",
        "To Be Filled By O.E.M.",
        "Not Specified",
        "  default string  ",
        "UNKNOWN",
        "n/a",
        "",
    ):
        got = serial({"serial": placeholder})
        assert got == "", f"{placeholder!r} survived as a serial: {got!r}"

    # Must-not-strip controls. Without these, a filter that returned "" for
    # everything would pass every assertion above.
    for real in ("FAKE-SERIAL-A", "FAKE-SERIAL-B", "FAKE-SERIAL-C"):
        assert serial({"serial": real}) == real, f"real serial {real!r} was discarded"

    # Whitespace is trimmed, not treated as content.
    assert serial({"serial": "  FAKE-SERIAL-A  "}) == "FAKE-SERIAL-A"


def main() -> None:
    """Run every assertion."""
    run({"hardware_devices": [], "hardware_modules": [], "wan_circuits": []}, [])
    check_dmi_placeholders_are_not_serials()
    print("nautobot_hardware_seed_serials: OK")


if __name__ == "__main__":
    main()
