#!/usr/bin/env python3
"""The unpoller unit drops mount-namespace sandboxing inside a container
(where it fails with status=226/NAMESPACE) and keeps it elsewhere, and it
starts unpoller with the role's config file."""

import unittest
from pathlib import Path

import jinja2

TEMPLATE = Path(__file__).resolve().parent.parent / "roles" / "unpoller" / "templates" / "unpoller.service.j2"


def render(container_rc):
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    return env.from_string(TEMPLATE.read_text()).render(
        ansible_managed="test",
        unpoller_version="0.0.0",
        unpoller_user="unpoller",
        _unpoller_virt_container={"rc": container_rc},
    )


class UnpollerUnitContainer(unittest.TestCase):
    def test_container_omits_namespace_sandboxing(self):
        unit = render(0)
        self.assertNotIn("ProtectSystem", unit)
        self.assertNotIn("PrivateTmp", unit)
        self.assertIn("NoNewPrivileges=true", unit)

    def test_unit_names_the_config_file(self):
        self.assertIn("ExecStart=/usr/local/bin/unpoller --config /etc/unpoller.conf", render(0))

    def test_host_keeps_namespace_sandboxing(self):
        unit = render(1)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertIn("PrivateTmp=true", unit)


if __name__ == "__main__":
    unittest.main()
