"""Catalog endpoints probe their public ingress URLs, including SSO routes.

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
DEFAULTS = Path(__file__).resolve().parent.parent / "roles/status_stack/defaults/main.yml"
EVAL_HEALTH_PROBES = yaml.safe_load(DEFAULTS.read_text())["status_stack_eval_health_probes"]
GUEST_HEALTH_PROBES = yaml.safe_load(DEFAULTS.read_text())["status_stack_guest_health_probes"]


def render(services: list[dict], dashboard_catalog_services: list[dict] | None = None,
           dashboard_catalog_base_domain: str = "example.test",
           monitor_targets: dict | None = None) -> dict[str, dict]:
    # If dashboard_catalog_services not specified, default to services for backward compatibility.
    if dashboard_catalog_services is None:
        dashboard_catalog_services = services

    env = jinja2.Environment(trim_blocks=True, undefined=jinja2.ChainableUndefined)
    env.filters["comment"] = lambda s: f"# {s}"
    env.filters["regex_replace"] = lambda s, pat, rep="": re.sub(pat, rep, s)
    text = env.from_string(TEMPLATE.read_text()).render(
        ansible_managed="managed",
        dashboard_catalog_services=dashboard_catalog_services,
        dashboard_catalog_services_monitor=services,
        dashboard_catalog_base_domain=dashboard_catalog_base_domain,
        dashboard_catalog_group_titles={"apps": "Apps", "media": "Media", "other": "Other"},
        status_stack_interval="60s",
        status_stack_catalog_status_overrides={},
        status_stack_authelia_error_patterns=["invalid_client"],
        status_stack_failure_threshold=3,
        status_stack_ntfy_priority_degraded=3,
        status_stack_ntfy_priority_urgent=5,
        status_stack_ntfy_url="https://ntfy.example.test/observability",
        status_stack_ntfy_topic_degraded="observability",
        status_stack_ntfy_topic_urgent="keystone",
        status_stack_ui_dashboard_heading="Homelab Status",
        status_stack_authelia_public_url="https://authelia.example.test",
        status_stack_deadman_token="test-token",
        status_stack_kuma_keystones=[],
        status_stack_oidc_clients=[],
        status_stack_authenticated_endpoints=[],
        status_stack_monitor_targets=(
            {"icmp": [], "tcp": [], "http": []}
            if monitor_targets is None else monitor_targets
        ),
        status_stack_eval_health_probes=EVAL_HEALTH_PROBES,
        status_stack_guest_health_probes=GUEST_HEALTH_PROBES,
        status_stack_deadman_endpoints=[],
    )
    return {ep["name"]: ep for ep in yaml.safe_load(text)["endpoints"]}


class GatusCatalogProbe(unittest.TestCase):
    def test_sso_row_uses_public_https_url_and_accepts_auth_gate(self):
        ep = render(services=[{"name": "app", "sso": True, "url": "https://app.example.test",
                      "probe_url": "http://guest:8080"}])["app"]
        self.assertEqual(ep["url"], "https://app.example.test")
        self.assertIn("[STATUS] < 500", ep["conditions"])
        self.assertIn("[CERTIFICATE_EXPIRATION] > 240h", ep["conditions"])

    def test_apex_row_uses_the_service_name_subdomain(self):
        ep = render(services=[{
            "name": "proxmox", "fqdn": "example.test",
            "url": "http://example.test:8006/", "probe_url": "https://node:8006",
        }])["proxmox"]
        self.assertEqual(ep["url"], "https://proxmox.example.test/")

    def test_public_row_keeps_the_public_url_and_cert_check(self):
        ep = render(services=[{"name": "pub", "sso": False, "url": "https://pub.example.test",
                      "probe_url": "http://guest:80"}])["pub"]
        self.assertEqual(ep["url"], "https://pub.example.test")
        self.assertEqual(ep["conditions"], [
            "[STATUS] < 500",
            "[STATUS] != 504",
            "[BODY] != pat(*invalid_client*)",
            "[RESPONSE_TIME] < 3000",
            "[CERTIFICATE_EXPIRATION] > 240h",
        ])

    def test_readiness_path_requires_http_200(self):
        ep = render(services=[{"name": "llm", "sso": False,
                      "url": "https://llm.example.test",
                      "probe_url": "http://router:4000",
                      "probe_path": "/health/readiness"}])["llm"]
        self.assertEqual(ep["url"], "https://llm.example.test/health/readiness")
        self.assertEqual(ep["conditions"], [
            "[STATUS] == 200",
            "[RESPONSE_TIME] < 3000",
            "[CERTIFICATE_EXPIRATION] > 240h",
        ])

    def test_homebox_api_path_requires_http_200(self):
        ep = render(services=[{"name": "homebox", "sso": True,
                      "url": "https://homebox.example.test",
                      "probe_url": "http://homebox:7745",
                      "probe_path": "/api/v1/status"}])["homebox"]
        self.assertEqual(ep["url"], "https://homebox.example.test/api/v1/status")
        self.assertEqual(ep["conditions"], [
            "[STATUS] == 200",
            "[RESPONSE_TIME] < 3000",
            "[CERTIFICATE_EXPIRATION] > 240h",
        ])

    def test_sso_row_without_a_probe_url_uses_the_public_url(self):
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
        monitor_apps = [
            {"name": "dash", "sso": True, "url": "https://dash.example.test",
             "probe_url": "http://dash-guest:3000", "ui": True, "dashboard": True},
        ]
        wall_apps = [
            {"name": "dash", "sso": True, "url": "https://dash.example.test",
             "probe_url": "http://dash-guest:3000", "ui": True, "dashboard": True},
            {"name": "wall-only", "sso": True, "url": "https://wall-only.example.test",
             "probe_url": "http://wall-guest:8080", "ui": True, "dashboard": False},
        ]
        # Simulate: dashboard_catalog_services_monitor has dash; wall also includes wall-only.
        # Wall-only must be added even though not in monitor.
        eps = render(
            services=monitor_apps,
            dashboard_catalog_services=wall_apps
        )
        # Both wall apps must appear in endpoints; wall-only deduped into single list.
        self.assertIn("dash", eps)
        self.assertIn("wall-only", eps)

    def test_specialist_eval_probes_leave_existing_endpoints_unchanged(self):
        monitor_targets = {
            "icmp": [
                {"name": "sim-placeholder", "fqdn": "192.0.2.21", "group": "guest",
                 "tags": ["specialist-eval", "sim-eval"]},
                {"name": "langflow-placeholder", "fqdn": "192.0.2.22", "group": "guest",
                 "tags": ["specialist-eval", "langflow-eval"]},
                {"name": "dify-placeholder", "fqdn": "192.0.2.23", "group": "guest",
                 "tags": ["specialist-eval", "dify-eval"]},
                {"name": "unknown-placeholder", "fqdn": "192.0.2.24", "group": "guest",
                 "tags": ["specialist-eval"]},
                {"name": "ordinary-placeholder", "fqdn": "192.0.2.25", "group": "guest",
                 "tags": ["terraform", "vm"]},
                {"name": "platform-only-placeholder", "fqdn": "192.0.2.26", "group": "guest",
                 "tags": ["sim-eval"]},
            ],
            "tcp": [{"name": "port-placeholder", "fqdn": "192.0.2.31", "port": 22, "group": "node"}],
            "http": [{"name": "http-placeholder", "fqdn": "192.0.2.32", "port": 8080,
                      "path": "/health", "expect_status": [200], "group": "service"}],
        }
        baseline_targets = {
            kind: [
                {key: value for key, value in target.items() if key != "tags"}
                for target in targets
            ]
            for kind, targets in monitor_targets.items()
        }

        baseline = render(services=[], monitor_targets=baseline_targets)
        rendered = render(services=[], monitor_targets=monitor_targets)
        eval_endpoints = {
            name: endpoint for name, endpoint in rendered.items() if name.startswith("eval-")
        }

        self.assertEqual(set(eval_endpoints), {
            "eval-sim-placeholder-sim-eval",
            "eval-langflow-placeholder-langflow-eval",
            "eval-dify-placeholder-dify-eval",
        })
        expected_urls = {
            "eval-sim-placeholder-sim-eval": "http://192.0.2.21:3000/api/health",
            "eval-langflow-placeholder-langflow-eval": "http://192.0.2.22:7860/health",
            "eval-dify-placeholder-dify-eval": "http://192.0.2.23:80/console/api/ping",
        }
        for name, url in expected_urls.items():
            with self.subTest(endpoint=name):
                endpoint = eval_endpoints[name]
                self.assertEqual(endpoint["url"], url)
                self.assertEqual(endpoint["group"], "guest")
                self.assertEqual(endpoint["conditions"], ["[STATUS] == 200"])

        existing_endpoints = {
            name: endpoint for name, endpoint in rendered.items() if not name.startswith("eval-")
        }
        self.assertEqual(existing_endpoints, baseline)

    def test_production_guest_probes_render_alongside_eval_probes(self):
        # Production Dify and Langflow get the same direct health probes as the
        # specialist-eval guests: the guest's own inventory address, group
        # "guest", named http-<guest>-health after the monitor_targets HTTP
        # convention. The eval probes keep rendering for their tagged guests.
        monitor_targets = {
            "icmp": [
                {"name": "dify", "fqdn": "192.0.2.41", "group": "guest",
                 "tags": ["dify"]},
                {"name": "langflow", "fqdn": "192.0.2.42", "group": "guest",
                 "tags": ["langflow"]},
                {"name": "dify-eval", "fqdn": "192.0.2.43", "group": "guest",
                 "tags": ["specialist-eval", "dify-eval"]},
                {"name": "ordinary", "fqdn": "192.0.2.44", "group": "guest",
                 "tags": ["terraform", "vm"]},
            ],
            "tcp": [],
            "http": [],
        }
        rendered = render(services=[], monitor_targets=monitor_targets)

        self.assertEqual(set(rendered), {
            "http-dify-health",
            "http-langflow-health",
            "eval-dify-eval-dify-eval",
        })
        expected_urls = {
            "http-dify-health": "http://192.0.2.41:80/console/api/ping",
            "http-langflow-health": "http://192.0.2.42:7860/health",
            "eval-dify-eval-dify-eval": "http://192.0.2.43:80/console/api/ping",
        }
        for name, url in expected_urls.items():
            with self.subTest(endpoint=name):
                endpoint = rendered[name]
                self.assertEqual(endpoint["url"], url)
                self.assertEqual(endpoint["group"], "guest")
                self.assertEqual(endpoint["conditions"], ["[STATUS] == 200"])


if __name__ == "__main__":
    unittest.main()
