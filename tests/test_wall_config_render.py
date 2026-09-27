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
        "wall_slides": [],
        "dashboard_catalog_services": [
            {"name": "alpha", "group": "apps", "ui": True},
            {"name": "bravo", "group": "apps", "ui": True},
            {"name": "hidden", "group": "apps", "ui": False},
            {"name": "charlie", "group": "media", "ui": True},
        ],
        "tofu_data": {
            "containers": {"a": {}, "b": {}},
            "vms": {"v": {}},
            "nodes": {
                "node-a": {"role": "compute"},
                "node-b": {"commissioned": False, "role": "old"},
                "node-c": {},
            },
        },
    }
    ctx.update(overrides)
    return json.loads(env.from_string(TEMPLATE.read_text()).render(**ctx))


class WallConfig(unittest.TestCase):
    def test_contract(self):
        cfg = render()
        self.assertEqual(cfg["groups"], [{"name": "apps", "apps": ["alpha", "bravo"]},
                                         {"name": "media", "apps": ["charlie"]}])
        # D2: a node with no distinct role maps to ITS OWN NAME (mc1.js reads
        # nodeRoles[name] === name as "no role"); node-b is decommissioned and
        # absent entirely.
        self.assertEqual(cfg["nodeRoles"], {"node-a": "compute", "node-c": "node-c"})
        self.assertEqual(cfg["guestCount"], 3)
        self.assertEqual(cfg["refreshSeconds"], 15)
        self.assertEqual(cfg["extraNodes"], [])
        # An empty wall_slides still carries the rotator's own MC1-MC5
        # defaults — the rotator schema treats a non-empty `slides` as a
        # REPLACEMENT of its built-ins, so config.json must always render
        # the full list, never wall_slides alone.
        self.assertEqual(cfg["slides"], [
            {"name": "MC1", "url": "/mc1/"},
            {"name": "MC2", "url": "/mc2/"},
            {"name": "MC3", "url": "/mc3/"},
            {"name": "MC4", "url": "/mc4/"},
            {"name": "MC5", "url": "/mc5/"},
        ])
        self.assertEqual(cfg["title"], "HOMELAB")

    def test_empty_catalog_renders_valid_json(self):
        cfg = render(dashboard_catalog_services=[], tofu_data={})
        self.assertEqual(cfg["groups"], [])
        self.assertEqual(cfg["guestCount"], 0)

    def test_glance_slide_appends_after_mc1_5_in_the_rotator_schema(self):
        slides = [{"name": "GLANCE", "url": "https://glance.example.test"}]
        cfg = render(wall_slides=slides)
        names = [s["name"] for s in cfg["slides"]]
        self.assertEqual(names, ["MC1", "MC2", "MC3", "MC4", "MC5", "GLANCE"])
        for slide in cfg["slides"]:
            self.assertEqual(set(slide.keys()) - {"seconds"}, {"name", "url"})
        glance = cfg["slides"][-1]
        self.assertTrue(glance["url"].startswith("https://"))
        self.assertEqual(glance["url"], "https://glance.example.test")

    def test_slide_seconds_is_optional_and_passed_through(self):
        slides = [{"name": "GLANCE", "url": "https://glance.example.test", "seconds": 20}]
        cfg = render(wall_slides=slides)
        self.assertEqual(cfg["slides"][-1], {"name": "GLANCE", "url": "https://glance.example.test", "seconds": 20})


if __name__ == "__main__":
    unittest.main()
