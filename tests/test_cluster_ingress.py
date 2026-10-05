"""Exercise production DNS ownership, router normalization, and ACME selection."""

from pathlib import Path
import unittest

import yaml
from ansible.template import trust_as_template

from test_openbao_denied_vs_absent_writes import _all, _find, _render

ROOT = Path(__file__).resolve().parents[1]
DNS = "roles/technitium_dns/tasks/main/ingress_and_apex.yml"
DNS_EXPLICIT_INGRESS = "roles/technitium_dns/tasks/main/explicit_ingress_names.yml"


class ClusterIngress(unittest.TestCase):
    def setUp(self):
        defaults = yaml.safe_load(
            (ROOT / "roles/technitium_dns/defaults/main/02-ingress-and-apex.yml").read_text()
        )
        self.variables = {
            key: trust_as_template(value) if isinstance(value, str) else value
            for key, value in defaults.items()
        }
        self.variables.update({
            "tofu_data": {"ingress": [{
                "name": "proxmox", "apex": True,
                "fqdn": "pve.example.com",
                "host_aliases": ["proxmox.example.com"],
                "tls_domains": ["pve.example.com", "proxmox.example.com"],
            }]},
            "technitium_dns_zone": "pve.example.com",
            "technitium_dns_apex_domain": "example.com",
            "technitium_dns_ingress_target_ip": "192.0.2.50",
            "technitium_dns_apply": True,
            "technitium_dns_role": "primary",
            "technitium_dns_proxmox_endpoint_a_records": [],
        })

    def test_canonical_child_and_parent_alias_use_one_ingress_target(self):
        names = _render("technitium_dns_explicit_ingress_names", self.variables)
        self.assertEqual(names, ["pve.example.com", "proxmox.example.com"])
        writer = _find(DNS_EXPLICIT_INGRESS, "Create explicitly named ingress A records")
        for role in ["primary", "secondary"]:
            for name, zone in [(names[0], "pve.example.com"), (names[1], "example.com")]:
                variables = dict(self.variables, item=name, technitium_dns_role=role)
                variables.update({key: trust_as_template(value) for key, value in writer["vars"].items()})
                self.assertEqual(_render("_ingress_record_zone", variables), zone)
                self.assertEqual(_all(writer["when"], variables), role == "primary" or zone == "example.com")
                self.assertEqual(_render(writer["ansible.builtin.uri"]["body"]["ipAddress"], variables, wrap=False), "192.0.2.50")

    def test_dns_ingress_aliases_match_router_hostname_fallback(self):
        route = dict(self.variables["tofu_data"]["ingress"][0])
        route.pop("apex")
        route.pop("hostname", None)
        blank_hostname_route = dict(route, name=route["fqdn"], hostname="")
        explicit_hostname_route = dict(route, hostname=route["host_aliases"][0])
        variables = dict(
            self.variables,
            tofu_data={"ingress": [route, explicit_hostname_route, blank_hostname_route]},
        )

        self.assertEqual(
            set(_render("technitium_dns_ingress_aliases", variables)),
            {route["name"], explicit_hostname_route["hostname"], blank_hostname_route["name"]},
        )
        aliases = _render("technitium_dns_ingress_aliases", variables)
        ingress_variables = dict(variables, technitium_dns_ingress_aliases=aliases)
        for task_name in [
            "Create Traefik ingress alias A records",
            "Create Traefik ingress alias apex A records",
        ]:
            writer = _find("roles/technitium_dns/tasks/main/ingress_and_apex.yml", task_name)
            writer_variables = dict(
                ingress_variables,
                item=route["name"],
                technitium_dns_role="primary",
                technitium_dns_apply=True,
            )
            self.assertIn(route["name"], _render(writer["loop"], writer_variables, wrap=False))
            self.assertEqual(
                _render(
                    writer["ansible.builtin.uri"]["body"]["ipAddress"],
                    writer_variables,
                    wrap=False,
                ),
                self.variables["technitium_dns_ingress_target_ip"],
            )

        host_ip = self.variables["technitium_dns_ingress_target_ip"]
        build_variables = dict(
            ingress_variables,
            item=route["name"],
            hostvars={
                route["name"]: {
                    "hostname": route["name"],
                    "container_ip": host_ip,
                }
            },
        )
        builder = _find("roles/technitium_dns/tasks/main/build_records.yml", "Build A records from inventory")
        self.assertFalse(_all(builder["when"], build_variables))

    def test_ingress_ownership_disables_legacy_apex_writer(self):
        self.assertTrue(_render("technitium_dns_cluster_ingress_owned", self.variables))
        task = _find("roles/technitium_dns/tasks/main/health_check.yml", "Configure the health-checked zone apex")
        variables = dict(self.variables, technitium_dns_apex_health_check_enabled=True)
        self.assertFalse(_all(task["when"], variables))
        variables["tofu_data"] = {"ingress": [{"name": "proxmox", "apex": True}]}
        self.assertTrue(_all(task["when"], variables))

    def test_apex_cleanup_removes_old_nodes_and_preserves_ingress_address(self):
        task = _find(DNS, "Delete existing Proxmox endpoint apex A records")
        records = [{"type": "A", "name": "pve.example.com", "rData": {"ipAddress": ip}} for ip in ["192.0.2.10", "192.0.2.50"]]
        variables = dict(self.variables, technitium_dns_existing_records={"json": {"response": {"records": records}}})
        self.assertEqual(_render(task["loop"], variables, wrap=False), records[:1])

    def test_failed_probes_preserve_dns_and_existing_writer(self):
        task = _find(DNS, "Require a reachable ingress before changing cluster DNS ownership")
        variables = dict(self.variables, technitium_dns_ingress_target_ip="",
                         technitium_dns_vip_probe={"failed": True},
                         technitium_dns_ingress_fallback_probe={"failed": True})
        self.assertFalse(_all(task["ansible.builtin.assert"]["that"], variables))
        variables["technitium_dns_ingress_target_ip"] = "192.0.2.50"
        self.assertFalse(_all(task["ansible.builtin.assert"]["that"], variables))
        variables["technitium_dns_ingress_fallback_probe"] = {"failed": False}
        self.assertTrue(_all(task["ansible.builtin.assert"]["that"], variables))
        tasks = yaml.safe_load((ROOT / DNS).read_text())
        names = [item["name"] for item in tasks]
        self.assertLess(names.index(task["name"]), names.index("Stop the legacy apex writer before ingress takes DNS ownership"))
        self.assertLess(names.index(task["name"]), names.index("Delete existing Proxmox endpoint apex A records"))

    def test_real_acme_default_selects_discovery_only_for_multizone(self):
        defaults = yaml.safe_load((ROOT / "roles/traefik/defaults/main.yml").read_text())
        expression = defaults["traefik_acme_route53_discovery"]
        variables = {"traefik_base_domain": "pve.example.com", "traefik_ingress_routes": self.variables["tofu_data"]["ingress"]}
        self.assertTrue(_render(expression, variables, wrap=False))
        variables["traefik_ingress_routes"] = [{"tls_domains": ["pve.example.com", "*.pve.example.com"]}]
        self.assertFalse(_render(expression, variables, wrap=False))

    def test_router_prefers_explicit_fqdn_over_legacy_apex_domain(self):
        task = _find("roles/traefik/tasks/routes.yml", "Build Traefik routers from the inventory ingress table")
        item = dict(self.variables["tofu_data"]["ingress"][0], fqdn="cluster.example.com", port=8006, backends=["node.example.com"])
        variables = {
            "item": item, "traefik_base_domain": "pve.example.com",
            "traefik_health_check_interval_overrides": {},
            "traefik_health_check_interval": "10s", "traefik_health_check_timeout": "5s",
        }
        routes = _render(task["ansible.builtin.set_fact"]["traefik_routes"], variables, wrap=False)
        self.assertEqual(routes[0]["fqdn"], "cluster.example.com")
        self.assertEqual(routes[0]["host_aliases"], ["proxmox.example.com"])


if __name__ == "__main__":
    unittest.main()
