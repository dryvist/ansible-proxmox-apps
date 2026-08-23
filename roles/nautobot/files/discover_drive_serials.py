#!/usr/bin/env python3
"""Discover physical drives from the live Proxmox nodes as a hardware slice.

Emits the same ``hardware_modules`` contract ``ssot_hardware.py`` already
consumes, so this is a new SOURCE for an existing pipeline — not a second
pipeline. Output goes to stdout and is meant to be piped into a temp file that
``INT_HOMELAB_HARDWARE`` points at for one converge.

WHY THIS EXISTS, and why it does not write a file into the repo
---------------------------------------------------------------
A drive's serial is a physical fact. Transcribing it into a markdown table
makes a copy that drifts the moment a disk moves, and this estate already has
one serial living in seven different markdown files as free prose. The device
itself is the only source that cannot be wrong, so discovery reads it and
Nautobot stores it — exactly one home each for the fact and the record.

``hardware/inventory.seed.yml`` in the inventory repo is the anti-pattern to
avoid repeating: a GENERATED artifact committed beside its own source, which
has already drifted (it records the R540 as unplugged while the machine is up).
Generated data belongs at converge time, never in version control.

GRAIN
-----
One row per PHYSICAL DRIVE, keyed ``DISK-<serial>``. This deliberately differs
from the model-level rows the markdown tables produce (``HDD-HGST-6TB`` with
``quantity: 3``), because a serial cannot attach to a record that represents
three drives. The model-level rows for drives are SUPERSEDED by these and must
be retired separately — ``ssot_hardware.py`` is additive by design and will not
remove them, so leaving both in place would mean two records for one drive.

Usage:
    discover_drive_serials.py pve-r540.example.com pve-r710.example.com ...
    discover_drive_serials.py --ssh-key ~/.ssh/id_rsa_pve node1 node2
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

# Vendor strings as they appear in lsblk MODEL, mapped to the manufacturer
# names already used by the seed bundle so ensure_module_type() reuses the
# existing ModuleType instead of creating a near-duplicate.
_VENDORS = {
    "HGST": "HGST",
    "TOSHIBA": "Toshiba",
    "SAMSUNG": "Samsung",
    "MICRON": "Micron",
    "INTEL": "Intel",
    "SEAGATE": "Seagate",
    "ST": "Seagate",
    "SSDSC": "Intel",
    "ADATA": "ADATA",
    "SANDISK": "SanDisk",
    "WDC": "Western Digital",
    "CRUCIAL": "Crucial",
    "KINGSTON": "Kingston",
}

# lsblk reports zvols and loop/ram devices as TYPE=disk too. Excluding by name
# prefix rather than by "has no serial": a real disk with an unreadable serial
# must still be reported (and then flagged), not silently dropped.
_VIRTUAL_PREFIXES = ("zd", "loop", "ram", "sr")


def _vendor_of(model: str) -> str:
    upper = model.upper()
    for token, name in _VENDORS.items():
        if upper.startswith(token) or f" {token}" in upper:
            return name
    return model.split()[0] if model else ""


def _probe(host: str, ssh_key: str | None) -> tuple[list[dict], set[str]]:
    """Return (lsblk rows, kernel names that are members of a zpool)."""
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if ssh_key:
        ssh += ["-i", ssh_key]
    ssh.append(f"root@{host}")

    remote = (
        "lsblk -dn --json -o NAME,SERIAL,MODEL,SIZE,ROTA,TYPE,RM; "
        "echo '---SPLIT---'; "
        "zpool status -LP 2>/dev/null | grep -oE '/dev/[a-z0-9]+' | sort -u"
    )
    out = subprocess.run(
        ssh + [remote], capture_output=True, text=True, timeout=90, check=True
    ).stdout

    raw, _, pooltext = out.partition("---SPLIT---")
    rows = json.loads(raw)["blockdevices"]

    # zpool reports partitions, and the two naming schemes differ:
    #   SCSI/SATA  /dev/sdc1     -> sdc
    #   NVMe       /dev/nvme0n1p3 -> nvme0n1     (note the "p")
    # Stripping trailing digits alone yields "nvme0n1p", which matches no
    # device, so every NVMe silently reads as "not in a pool" — which is how
    # the 4TB Samsung and the ADATA first came out flagged as spares while
    # both were live rpool members.
    # A whole-disk vdev is reported without a partition ("nvme0n1"), and that
    # name legitimately ends in a digit — so a blanket digit-strip would turn it
    # into "nvme0n" and lose it. Keep the reported name AND its de-partitioned
    # form; looking up only real lsblk disk names makes the extra entry inert.
    in_pool = set()
    for path in pooltext.split():
        if not path.startswith("/dev/"):
            continue
        name = path.rsplit("/", 1)[-1]
        in_pool.add(name)
        in_pool.add(re.sub(r"p\d+$" if "nvme" in name else r"\d+$", "", name))
    return rows, in_pool


def discover(hosts: list[str], ssh_key: str | None) -> tuple[list[dict], list[str]]:
    modules: list[dict] = []
    warnings: list[str] = []
    seen: dict[str, str] = {}

    for host in hosts:
        node = host.split(".")[0]
        try:
            rows, in_pool = _probe(host, ssh_key)
        except Exception as exc:  # noqa: BLE001 - a dead node must not be silent
            warnings.append(f"{node}: UNREACHABLE ({exc}) — its drives are NOT in this slice")
            continue

        for row in rows:
            name = row.get("name", "")
            if name.startswith(_VIRTUAL_PREFIXES) or row.get("type") != "disk":
                continue

            # A BMC's virtual media (LCDRIVE, Virtual Floppy) enumerates as a
            # real TYPE=disk with a MODEL and even a shared serial — on pve-r710
            # both report "20120430". They are 0B, and a zero-capacity drive is
            # never a drive, so size is the honest discriminator here.
            size = (row.get("size") or "").strip()
            if size in ("", "0B", "0"):
                continue

            # Removable media (a uSD reader, a USB installer stick) enumerates
            # as a serial-bearing disk and would otherwise be seeded as estate
            # storage — permanently, since the seed job never deletes. `rm` is
            # the honest discriminator; a model-name blocklist would rot.
            if str(row.get("rm", "")).lower() in ("1", "true"):
                continue

            serial = (row.get("serial") or "").strip()
            model = (row.get("model") or "").strip()
            if not serial:
                warnings.append(f"{node}:{name} model={model!r} has NO readable serial — skipped")
                continue

            hw_id = f"DISK-{serial}"
            if hw_id in seen:
                # The same serial on two hosts is a real condition worth seeing
                # (a moved disk mid-sweep, or a vendor reusing a serial), not
                # something to silently collapse.
                warnings.append(
                    f"DUPLICATE serial {serial}: {seen[hw_id]} and {node}:{name} — kept the first"
                )
                continue
            seen[hw_id] = f"{node}:{name}"

            installed = name in in_pool
            modules.append(
                {
                    "hw_id": hw_id,
                    "quantity": 1,
                    "category": "Drive",
                    "manufacturer": _vendor_of(model),
                    "model": model,
                    "part_number": "",
                    "serial": serial,
                    "status": "Active" if installed else "Inventory",
                    "status_note": (
                        f"in a zpool on {node}" if installed else f"present on {node}, not in a pool"
                    ),
                    "location_note": node,
                    "location": node,
                    "installed_in": node if installed else None,
                    "purchased": "",
                    "price": "",
                    "section": "Storage",
                }
            )
    return modules, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hosts", nargs="+", help="node FQDNs or hostnames")
    parser.add_argument("--ssh-key", default=None)
    args = parser.parse_args()

    modules, warnings = discover(args.hosts, args.ssh_key)

    for line in warnings:
        print(f"WARNING: {line}", file=sys.stderr)

    # Fail loudly rather than emit an empty slice. ssot_hardware.py treats an
    # empty slice as "nothing to do" and returns success, so a silent empty
    # render would look exactly like a converge that had nothing to change.
    if not modules:
        print("ERROR: discovered zero drives — refusing to emit an empty slice", file=sys.stderr)
        return 1

    print("---")
    print("# GENERATED by discover_drive_serials.py from the live nodes.")
    print("# Do NOT commit this. Regenerate it per converge; the drives are the source.")
    print('schema_version: "1.0.0"')
    print(f"source: \"live discovery: {' '.join(args.hosts)}\"")
    print("hardware_devices: []")
    print("hardware_modules:")
    for row in modules:
        print("  - " + json.dumps(row))
    print(f"# {len(modules)} drives discovered, {len(warnings)} warning(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
