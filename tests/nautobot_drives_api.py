"""Guard the Proxmox API source for Nautobot’s delete-capable drive sync."""
from __future__ import annotations

import importlib.util
import inspect
import json
import os
import ssl
import sys
import types
import urllib.error
from pathlib import Path
from unittest.mock import patch

JOBS = Path(__file__).resolve().parents[1] / "roles/nautobot/files/jobs"
API_ENV = {
    "NAUTOBOT_PROXMOX_API_URL": "https://pve.example.invalid",
    "NAUTOBOT_PROXMOX_TOKEN_ID": "nautobot@pve!inventory",
    "NAUTOBOT_PROXMOX_TOKEN_SECRET": "test-token-secret",
    "NAUTOBOT_PROXMOX_CA": "-----BEGIN CERTIFICATE-----\nexample\n-----END CERTIFICATE-----",
}


def install_job_stubs() -> None:
    """Install the smallest fake modules that let ssot_drives import.

    The API guards fail before a Nautobot model or adapter is needed.
    """
    diffsync = types.ModuleType("diffsync")
    diffsync.Adapter = type("Adapter", (), {"__init__": lambda self, *a, **k: None})

    jobs_mod = types.ModuleType("nautobot.apps.jobs")
    jobs_mod.register_jobs = lambda *a, **k: None

    dcim = types.ModuleType("nautobot.dcim.models")
    dcim.Device = type("Device", (), {})
    dcim.InventoryItem = type("InventoryItem", (), {})

    contrib = types.ModuleType("nautobot_ssot.contrib")
    contrib.NautobotModel = type("NautobotModel", (), {})
    contrib.NautobotAdapter = type("NautobotAdapter", (), {})

    base = types.ModuleType("nautobot_ssot.jobs.base")
    base.DataSource = type("DataSource", (), {"logger": None})

    common = types.ModuleType("ssot_common")
    common.ensure_manufacturer = lambda *a, **k: None
    common.MANUFACTURER = "Generic"

    for name, mod in {
        "diffsync": diffsync,
        "nautobot.apps": types.ModuleType("nautobot.apps"),
        "nautobot.apps.jobs": jobs_mod,
        "nautobot.dcim": types.ModuleType("nautobot.dcim"),
        "nautobot.dcim.models": dcim,
        "nautobot_ssot": types.ModuleType("nautobot_ssot"),
        "nautobot_ssot.contrib": contrib,
        "nautobot_ssot.jobs": types.ModuleType("nautobot_ssot.jobs"),
        "nautobot_ssot.jobs.base": base,
        "ssot_common": common,
    }.items():
        sys.modules[name] = mod


def load_api():
    """Import the stdlib-only PVE API client."""
    spec = importlib.util.spec_from_file_location("proxmox_disks", JOBS / "proxmox_disks.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["proxmox_disks"] = module
    spec.loader.exec_module(module)
    return module


def load_job():
    """Import ssot_drives.py and its API client against the stubs."""
    load_api()
    spec = importlib.util.spec_from_file_location("ssot_drives", JOBS / "ssot_drives.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["ssot_drives"] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    """Minimal context-managed urllib response for a JSON API payload."""

    def __init__(self, data):
        self.body = json.dumps({"data": data}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


def fake_opener(payloads, calls):
    """Return queued fake data and retain requests for contract assertions."""
    def open_request(request, *, context, timeout):
        calls.append((request, context, timeout))
        payload = payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)

    return open_request


def check_api_safety(api_mod, drives_mod) -> None:
    """Guard the delete-capable sync against incomplete or unsafe API reads."""
    real_context = ssl.create_default_context
    ca_values = []

    def make_context(*, cadata):
        ca_values.append(cadata)
        return real_context()

    with patch.object(api_mod.ssl, "create_default_context", side_effect=make_context):
        with patch.dict(os.environ, {}, clear=True):
            try:
                api_mod.ProxmoxDiskClient.from_env()
            except ValueError as exc:
                message = str(exc)
                assert all(name in message for name in API_ENV), message
            else:
                raise AssertionError("missing Proxmox settings did not fail")

        calls = []
        with patch.dict(os.environ, API_ENV, clear=True), patch.object(
            api_mod.urllib.request,
            "urlopen",
            side_effect=fake_opener([[{"node": "pve1", "status": "offline"}]], calls),
        ):
            job = drives_mod.SyncDrivesFromProxmox()
            job.source_adapter = None
            try:
                job.load_source_adapter()
            except ValueError as exc:
                assert "not online" in str(exc), str(exc)
            else:
                raise AssertionError("offline node was accepted")
            assert job.source_adapter is None, "source adapter loaded before cluster validation"
            assert len(calls) == 1, "disk request followed an offline node response"

        calls = []
        with patch.dict(os.environ, API_ENV, clear=True), patch.object(
            api_mod.urllib.request,
            "urlopen",
            side_effect=fake_opener([[{"node": "pve1", "status": "online"}], []], calls),
        ):
            job = drives_mod.SyncDrivesFromProxmox()
            job.source_adapter = None
            try:
                job.load_source_adapter()
            except ValueError as exc:
                assert "zero disks" in str(exc), str(exc)
            else:
                raise AssertionError("empty disk list was accepted")
            assert job.source_adapter is None, "source adapter loaded after an empty disk list"

        calls = []
        disks = [
            {"devpath": "/dev/sda", "type": "hdd", "serial": "SERIAL1"},
            {"devpath": "/dev/sdb", "type": "usb", "serial": "USB1"},
        ]
        with patch.dict(os.environ, API_ENV, clear=True), patch.object(
            api_mod.urllib.request,
            "urlopen",
            side_effect=fake_opener([[{"node": "pve1", "status": "online"}], disks], calls),
        ):
            rows = api_mod.ProxmoxDiskClient.from_env().rows()
        assert rows == [{**disks[0], "node": "pve1"}], rows
        assert ca_values[-1] == API_ENV["NAUTOBOT_PROXMOX_CA"], "CA PEM was not supplied"
        escaped = {**API_ENV, "NAUTOBOT_PROXMOX_CA": API_ENV["NAUTOBOT_PROXMOX_CA"].replace("\n", "\\n")}
        with patch.dict(os.environ, escaped, clear=True):
            api_mod.ProxmoxDiskClient.from_env()
        assert ca_values[-1] == API_ENV["NAUTOBOT_PROXMOX_CA"], "escaped PEM newlines were not restored"
        for request, context, timeout in calls:
            assert request.get_header("Authorization") == (
                "PVEAPIToken=nautobot@pve!inventory=test-token-secret"
            )
            assert context.check_hostname is True
            assert context.verify_mode == ssl.CERT_REQUIRED
            assert timeout == 30

        calls = []
        with patch.dict(os.environ, API_ENV, clear=True), patch.object(
            api_mod.urllib.request,
            "urlopen",
            side_effect=fake_opener(
                [urllib.error.URLError(API_ENV["NAUTOBOT_PROXMOX_TOKEN_SECRET"])], calls
            ),
        ):
            try:
                api_mod.ProxmoxDiskClient.from_env().rows()
            except ValueError as exc:
                assert API_ENV["NAUTOBOT_PROXMOX_TOKEN_SECRET"] not in str(exc)
                assert exc.__suppress_context__, "raw urllib error remains in the traceback"
            else:
                raise AssertionError("API error did not fail the source read")


def check_serial_rule(drives_mod) -> None:
    """A serial that merely repeats the WWN is not a serial."""
    same = drives_mod._same_identifier

    assert same("0x5000cca25dc1b2a3", "5000cca25dc1b2a3"), "0x prefix must normalise"
    assert same("5000CCA25DC1B2A3", "5000cca25dc1b2a3"), "comparison must be case-insensitive"

    # The must-NOT-mangle control. An earlier revision also stripped a leading
    # "3" (the SCSI-name prefix in scsi-3<wwn>), which corrupts any real serial
    # beginning with 3 — the estate carries one. Without this case, that bug
    # passes every other assertion here.
    assert not same("3ABC123", "ABC123"), (
        "a leading 3 is being stripped — that silently mangles real serials "
        "that happen to start with 3"
    )

    assert not same("", "5000cca25dc1b2a3"), "an absent serial is not a WWN match"
    assert not same("EXAMPLESERIAL1", ""), "an absent WWN cannot prove anything"
    assert not same("EXAMPLESERIAL1", "5000cca25dc1b2a3"), "distinct values must not match"


def check_manufacturer_never_placeholder(drives_mod) -> None:
    """A manufacturer name must always be one that can exist.

    contrib resolves ``manufacturer__name`` to a real Manufacturer and raises
    ObjectNotCreated when it is absent — and nautobot_ssot records that as a
    per-object error while still finishing the job SUCCESS. So an invented name
    costs the whole record silently.

    Proxmox reports a LITERAL "unknown" in `vendor` for NVMe, not an empty
    string, so `vendor or fallback` keeps it. That lost all 19 drives on the
    first live run, with a clean-looking sync and an empty table.
    """
    name = drives_mod._manufacturer_name
    generic = drives_mod.GENERIC_MANUFACTURER

    # The exact live failure.
    assert name("unknown", "Samsung SSD 990 EVO Plus 4TB") != "unknown", (
        "a literal 'unknown' vendor is still being used as a Manufacturer name"
    )
    # Falls back to the model's leading word, which is a real make.
    assert name("unknown", "Samsung SSD 990 EVO Plus 4TB") == "Samsung", name(
        "unknown", "Samsung SSD 990 EVO Plus 4TB"
    )
    # No vendor and no usable model -> the honest generic, never empty.
    for placeholder in ("", "  ", "-", "N/A", "none", "NULL", "?"):
        got = name(placeholder, "")
        assert got == generic, f"{placeholder!r} -> {got!r}, expected {generic!r}"
        assert got, "an empty manufacturer name cannot resolve to an object"

    # A real vendor must survive untouched — without this, a fix that always
    # returned the generic would pass every assertion above.
    assert name("HGST", "HUS726060ALE610") == "HGST"


def check_not_null_fields(drives_mod) -> None:
    """Absent text values must be "", never None, and discovered must be set.

    `part_id`, `serial` and `description` map to CharFields that are
    `blank=True` but **NOT NULL**. Passing None raises IntegrityError mid-sync
    and aborts the whole run — and it lands on exactly the drives whose serial
    this job deliberately refuses to fabricate, so the correct-by-design case
    is the one that breaks.

    `discovered` must be an attribute: it defaults False on the model while
    get_queryset() filters on True, so leaving it unset writes rows the adapter
    cannot see. Every later run then re-creates them and collides on the
    (device, name) unique constraint, while the rows sit there invisible.
    """
    model = drives_mod.DriveInventoryItem
    hints = getattr(model, "__annotations__", {})

    for field in ("part_id", "serial", "description"):
        default = getattr(model, field, None)
        assert default == "", (
            f"{field} defaults to {default!r}; it maps to a NOT NULL column, so "
            'an absent value must be "" — None aborts the sync with IntegrityError'
        )
        assert "Optional" not in str(hints.get(field, "")), (
            f"{field} is typed Optional, which invites None into a NOT NULL column"
        )

    assert "discovered" in model._attributes, (
        "discovered is not a synced attribute — rows would be written with "
        "discovered=False, invisible to get_queryset(), and every rerun would "
        "collide on (device, name)"
    )
    assert getattr(model, "discovered", None) is True, "discovered must default True"


def check_post_run_verifies(drives_mod) -> None:
    """The job must fail when the rows it reported creating are not there."""
    assert hasattr(drives_mod.SyncDrivesFromProxmox, "post_run"), (
        "no post_run verification — nautobot_ssot reports SUCCESS even when "
        "every create raised, so the job must check the rows landed."
    )
    source = inspect.getsource(drives_mod.SyncDrivesFromProxmox.post_run)
    assert "raise" in source, "post_run must FAIL, not just log, on a short count"



if __name__ == "__main__":
    install_job_stubs()
    drives_mod = load_job()
    api_mod = sys.modules["proxmox_disks"]
    check_api_safety(api_mod, drives_mod)
    check_serial_rule(drives_mod)
    check_manufacturer_never_placeholder(drives_mod)
    check_not_null_fields(drives_mod)
    check_post_run_verifies(drives_mod)

    print("nautobot drive sync: API guards, TLS/auth, token-redaction, model checks OK")
