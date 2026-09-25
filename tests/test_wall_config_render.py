"""roles/wall renders the config.json contract homelab-wall reads.

Groups come from the catalog's UI rows (the names Gatus reports under), node
roles from commissioned nodes only.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import jinja2

TEMPLATE = Path(__file__).resolve().parent.parent / "roles/wall/templates/config.json.j2"


def render(**overrides) -> dict:
    env = jinja2.Environment(trim_blocks=True)
    env.filters["to_nice_json"] = lambda v: json.dumps(v, indent=4, sort_keys=True)
    ctx = {
        "wall_title": "HOMELAB",
        "wall_refresh_seconds": "15",
        "wall_extra_nodes": [],
        "dashboard_catalog_services": [
            {"name": "alpha", "group": "apps", "ui": True},
            {"name": "bravo", "group": "apps", "ui": True},
            {"name": "hidden", "group": "apps", "ui": False},
            {"name": "charlie", "group": "media", "ui": True},
        ],
        "tofu_data": {
            "containers": {"a": {}, "b": {}},
            "vms": {"v": {}},
            "nodes": {"node-a": {"role": "compute"}, "node-b": {"commissioned": False, "role": "old"}},
        },
    }
    ctx.update(overrides)
    return json.loads(env.from_string(TEMPLATE.read_text()).render(**ctx))


class WallConfig(unittest.TestCase):
    def test_contract(self):
        cfg = render()
        self.assertEqual(cfg["groups"], [{"name": "apps", "apps": ["alpha", "bravo"]},
                                         {"name": "media", "apps": ["charlie"]}])
        self.assertEqual(cfg["nodeRoles"], {"node-a": "compute"})
        self.assertEqual(cfg["guestCount"], 3)
        self.assertEqual(cfg["refreshSeconds"], 15)
        self.assertEqual(cfg["extraNodes"], [])
        self.assertEqual(cfg["title"], "HOMELAB")

    def test_empty_catalog_renders_valid_json(self):
        cfg = render(dashboard_catalog_services=[], tofu_data={})
        self.assertEqual(cfg["groups"], [])
        self.assertEqual(cfg["guestCount"], 0)


if __name__ == "__main__":
    unittest.main()
