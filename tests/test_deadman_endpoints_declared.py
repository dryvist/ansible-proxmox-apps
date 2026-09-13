"""Every service_deadman check has a matching Gatus external endpoint.

The validator reports to `deadman_<name>`; Gatus rejects a report for an
endpoint its config does not declare, so a check added to
roles/service_deadman without its status_stack_deadman_endpoints entry would
page nowhere on the Gatus side and nothing would say so.
"""

from __future__ import annotations

import re
from pathlib import Path

ROLES = Path(__file__).resolve().parent.parent / "roles"


def _names(text: str, pattern: str) -> set[str]:
    return set(re.findall(pattern, text, flags=re.MULTILINE))


def test_every_deadman_check_has_a_gatus_endpoint():
    checks = _names(
        (ROLES / "service_deadman/defaults/main.yml").read_text(),
        r"^\s+- name: ([a-z0-9-]+)$",
    )
    endpoints = _names(
        (ROLES / "status_stack/defaults/main.yml").read_text(),
        r"^\s+- \{ name: ([a-z0-9-]+), heartbeat: [0-9]+[smh] \}$",
    )
    assert checks, "no service_deadman checks parsed"
    assert checks <= endpoints, f"checks without a Gatus deadman endpoint: {sorted(checks - endpoints)}"
