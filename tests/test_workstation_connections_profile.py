"""Exercise the production configuration publication and permission gates."""

from copy import deepcopy
import unittest

from test_openbao_denied_vs_absent_writes import _all, _find, _render

PROFILE = "roles/workstation_connections/tasks/main.yml"

class ConnectionProfile(unittest.TestCase):
    def setUp(self):
        self.profile = {"url": "https://pve.example.com", "type": "pve", "auth_method": "traditional", "credential_mount": "secret", "credential_path": "apps/cluster-client"}

    def test_publish_exact_inventory_profile_with_cas_and_idempotence(self):
        task = _find(PROFILE, "Publish the inventory-derived workstation connection profile")
        variables = {"workstation_connections_profile": self.profile, "workstation_connections_existing": {"secret": deepcopy(self.profile), "metadata": {"version": 7}}}
        self.assertFalse(_all(task["when"], variables))
        variables["workstation_connections_existing"]["secret"]["url"] = "https://old.example.com"
        self.assertTrue(_all(task["when"], variables))
        data = task["community.hashi_vault.vault_write"]["data"]
        self.assertEqual(_render(data["data"], variables, wrap=False), self.profile)
        self.assertEqual(_render(data["options"]["cas"], variables, wrap=False), 7)

    def test_denied_read_and_denied_capability_cannot_publish(self):
        read_gate = _find(PROFILE, "Reject configuration read errors other than absent document")
        for message, expected in [("Forbidden: Permission Denied", False), ("Invalid or missing path ['proxman/main']", True)]:
            self.assertEqual(_all(read_gate["ansible.builtin.assert"]["that"], {"workstation_connections_existing": {"msg": message}}), expected)
        cap_gate = _find(PROFILE, "Require configuration read and create or update capability")
        for capabilities, expected in [(["read", "update"], True), (["read"], False), (["deny"], False)]:
            variables = {"workstation_connections_capabilities": {"data": {"data": {"config/data/proxman/main": capabilities}}}}
            self.assertEqual(_all(cap_gate["ansible.builtin.assert"]["that"], variables), expected)

if __name__ == "__main__":
    unittest.main()
