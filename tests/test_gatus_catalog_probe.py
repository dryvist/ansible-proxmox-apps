"""Catalog endpoints behind SSO probe the guest, not the Authelia login page.

Renders roles/status_stack/templates/gatus-config.yaml.j2 with Ansible's
template defaults (trim_blocks on, lstrip_blocks off) and parses the YAML.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import jinja2
import yaml

TEMPLATE = Path(__file__).resolve().parent.parent / "roles/status_stack/templates/gatus-config.yaml.j2"


def render(services: list[dict]) -> dict[str, dict]:
    env = jinja2.Environment(trim_blocks=True, undefined=jinja2.ChainableUndefined)
    env.filters["comment"] = lambda s: f"# {s}"
    env.filters["regex_replace"] = lambda s, pat, rep="": re.sub(pat, rep, s)
    text = env.from_string(TEMPLATE.read_text()).render(
        ansible_managed="managed",
        dashboard_catalog_services=services,
        status_stack_interval="60s",
        status_stack_catalog_status_overrides={},
        status_stack_authelia_error_patterns=["invalid_client"],
        status_stack_failure_threshold=3,
        status_stack_ntfy_priority_degraded=3,
        status_stack_ntfy_priority_urgent=5,
    )
    return {ep["name"]: ep for ep in yaml.safe_load(text)["endpoints"]}


class GatusCatalogProbe(unittest.TestCase):
    def test_sso_row_probes_the_guest_without_a_cert_check(self):
        ep = render([{"name": "app", "sso": True, "url": "https://app.example.test",
                      "probe_url": "http://guest:8080"}])["app"]
        self.assertEqual(ep["url"], "http://guest:8080")
        self.assertFalse(any("CERTIFICATE" in c for c in ep["conditions"]))

    def test_public_row_keeps_the_public_url_and_cert_check(self):
        ep = render([{"name": "pub", "sso": False, "url": "https://pub.example.test",
                      "probe_url": "http://guest:80"}])["pub"]
        self.assertEqual(ep["url"], "https://pub.example.test")
        self.assertIn("[CERTIFICATE_EXPIRATION] > 240h", ep["conditions"])

    def test_sso_row_without_a_probe_url_falls_back_to_the_public_url(self):
        ep = render([{"name": "pool", "sso": True, "url": "https://pool.example.test",
                      "probe_url": ""}])["pool"]
        self.assertEqual(ep["url"], "https://pool.example.test")
        self.assertIn("[CERTIFICATE_EXPIRATION] > 240h", ep["conditions"])


if __name__ == "__main__":
    unittest.main()
