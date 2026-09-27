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


def render(services: list[dict] = None, dashboard_catalog_services: list[dict] = None,
           services_in_monitor: list[dict] = None) -> dict[str, dict]:
    # For backward compatibility, if services is provided as positional arg, use it for monitor.
    if services is None:
        services = services_in_monitor or []
    if dashboard_catalog_services is None:
        dashboard_catalog_services = services

    env = jinja2.Environment(trim_blocks=True, undefined=jinja2.ChainableUndefined)
    env.filters["comment"] = lambda s: f"# {s}"
    env.filters["regex_replace"] = lambda s, pat, rep="": re.sub(pat, rep, s)
    text = env.from_string(TEMPLATE.read_text()).render(
        ansible_managed="managed",
        dashboard_catalog_services=dashboard_catalog_services,
        dashboard_catalog_services_monitor=services,
        dashboard_catalog_group_titles={"apps": "Apps", "media": "Media", "other": "Other"},
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
        ep = render(services=[{"name": "app", "sso": True, "url": "https://app.example.test",
                      "probe_url": "http://guest:8080"}])["app"]
        self.assertEqual(ep["url"], "http://guest:8080")
        self.assertFalse(any("CERTIFICATE" in c for c in ep["conditions"]))

    def test_public_row_keeps_the_public_url_and_cert_check(self):
        ep = render(services=[{"name": "pub", "sso": False, "url": "https://pub.example.test",
                      "probe_url": "http://guest:80"}])["pub"]
        self.assertEqual(ep["url"], "https://pub.example.test")
        self.assertIn("[CERTIFICATE_EXPIRATION] > 240h", ep["conditions"])

    def test_sso_row_without_a_probe_url_falls_back_to_the_public_url(self):
        ep = render(services=[{"name": "pool", "sso": True, "url": "https://pool.example.test",
                      "probe_url": ""}])["pool"]
        self.assertEqual(ep["url"], "https://pool.example.test")
        self.assertIn("[CERTIFICATE_EXPIRATION] > 240h", ep["conditions"])

    def test_a_dashboard_false_compat_route_still_gets_its_own_endpoint(self):
        # dashboard:false hides a compat route (e.g. llm-ui-legacy) from every
        # board tile, but the route still fronts a real backend — a broken
        # compat redirect is still a real outage, so Gatus must monitor it
        # even though dashboard_catalog_services (the board-facing fact) drops
        # it entirely.
        eps = render(services=[{"name": "llm-ui-legacy", "sso": True,
                       "url": "https://llm.example.test/ui",
                       "probe_url": "http://guest:4000", "dashboard": False}])
        self.assertIn("llm-ui-legacy", eps)

    def test_every_wall_app_gets_a_gatus_endpoint(self):
        # The wall shows apps from dashboard_catalog_services | selectattr('ui').
        # Gatus must explicitly monitor each one, even if it's not in
        # dashboard_catalog_services_monitor (a wall-only entry).
        wall_apps = [
            {"name": "dash", "sso": True, "url": "https://dash.example.test",
             "probe_url": "http://192.0.2.10:3000", "ui": True, "dashboard": True},
            {"name": "wall-only", "sso": True, "url": "https://wall.example.test",
             "probe_url": "http://192.0.2.11:8080", "ui": True, "dashboard": False},
        ]
        # Simulate: dashboard_catalog_services_monitor omits wall-only; Gatus must still monitor it.
        eps = render(
            dashboard_catalog_services=[wall_apps[0], wall_apps[1]],
            services_in_monitor=[wall_apps[0]]  # Only the dashboard:true app
        )
        # Both wall apps must appear in endpoints, even though wall-only is not in monitor.
        self.assertIn("dash", eps)
        self.assertIn("wall-only", eps)


if __name__ == "__main__":
    unittest.main()
