"""ntfy publisher URL defaults.

Every `*ntfy*url` / `*ntfy*base` default under roles/ (outside the hub role)
names the ingress domain and no loopback address. The Gatus alerting provider
reads the shared status_stack_ntfy_url variable.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROLES = Path(__file__).resolve().parent.parent / "roles"
LOOPBACK = re.compile(r"127\.\d+\.\d+\.\d+|localhost|\[::1\]|0\.0\.0\.0")
NTFY_URL_KEY = re.compile(r"^[a-z0-9_]*ntfy[a-z0-9_]*(?:url|base)$")
# The hub's own role defines the hub address; every other role publishes through ingress.
HUB_ROLES = {"ntfy_docker"}


def _ntfy_url_defaults() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(ROLES.glob("*/defaults/**/*.yml")):
        if path.relative_to(ROLES).parts[0] in HUB_ROLES:
            continue
        data = yaml.safe_load(path.read_text()) or {}
        for key, value in data.items():
            if NTFY_URL_KEY.match(key) and isinstance(value, str) and value.strip():
                found[f"{path.relative_to(ROLES)}:{key}"] = value
    return found


def test_ntfy_url_defaults_are_found():
    assert "status_stack/defaults/main.yml:status_stack_ntfy_url" in _ntfy_url_defaults()


def test_no_publisher_defaults_to_a_loopback_ntfy_url():
    bad = {k: v for k, v in _ntfy_url_defaults().items() if LOOPBACK.search(v)}
    assert not bad, f"ntfy publisher defaults point at the local host: {bad}"


def test_publishers_default_to_the_ingress_domain():
    bad = {
        k: v
        for k, v in _ntfy_url_defaults().items()
        if "ingress_domain" not in v and "PROXMOX_SUBDOMAIN" not in v
    }
    assert not bad, f"ntfy publisher defaults bypass the ingress domain: {bad}"


def test_gatus_alerting_uses_the_shared_ntfy_url():
    template = (ROLES / "status_stack/templates/gatus-config.yaml.j2").read_text()
    assert re.search(r'^\s+url: "\{\{ status_stack_ntfy_url \}\}"$', template, flags=re.MULTILINE)
