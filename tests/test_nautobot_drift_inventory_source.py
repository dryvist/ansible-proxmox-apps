"""Nautobot playbooks use the inventory resolver's parsed inventory data."""

from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[1]
PLAYBOOKS = (
    "playbooks/nautobot-drift.yml",
    "playbooks/nautobot-sync-in.yml",
)


class NautobotInventorySource(unittest.TestCase):
    def test_playbooks_use_resolved_data_without_reparsing_its_path(self):
        for relative_path in PLAYBOOKS:
            with self.subTest(playbook=relative_path):
                source = (REPO / relative_path).read_text(encoding="utf-8")

                self.assertIn("dryvist.homelab.inventory_resolve", source)
                self.assertNotIn("tofu_inventory_resolved | from_json", source)


if __name__ == "__main__":
    unittest.main()
