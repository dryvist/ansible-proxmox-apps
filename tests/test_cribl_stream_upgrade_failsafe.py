#!/usr/bin/env python3
"""The Cribl Stream upgrade never leaves the node stopped.

roles/cribl_stream/tasks/upgrade.yml stops the service, replaces the binary
and starts it again. Two guarantees, checked structurally:

1. Both downloads (tarball and .sha256) are HEAD-checked before the stop, so
   an unpublished artifact fails the run with the service still up.
2. Every task from the stop onward sits in a block whose rescue starts the
   service again and then still fails the run.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
UPGRADE = ROOT / "roles" / "cribl_stream" / "tasks" / "upgrade.yml"


def _module(task):
    return next(
        (k for k in task if k.startswith("ansible.builtin.") or k.startswith("community.")),
        None,
    )


class CriblStreamUpgradeFailsafe(unittest.TestCase):
    def setUp(self):
        tasks = yaml.safe_load(UPGRADE.read_text())
        outer = [t for t in tasks if "block" in t]
        self.assertEqual(len(outer), 1, "expected one version-gated upgrade block")
        self.outer = outer[0]["block"]

    def _stop_block(self):
        inner = [t for t in self.outer if "block" in t]
        self.assertEqual(len(inner), 1, "expected one stop/replace/restart block")
        return inner[0]

    def test_preflight_heads_both_artifacts_before_the_stop(self):
        names = [t.get("name", "") for t in self.outer]
        stop_at = next(i for i, t in enumerate(self.outer) if "block" in t)
        heads = [
            t for t in self.outer[:stop_at]
            if _module(t) == "ansible.builtin.uri" and t["ansible.builtin.uri"].get("method") == "HEAD"
        ]
        self.assertEqual(len(heads), 1, f"no HEAD preflight before the stop block: {names}")
        urls = heads[0]["loop"]
        self.assertIn("{{ cribl_stream_tarball_url }}", urls)
        self.assertIn("{{ cribl_stream_tarball_url }}.sha256", urls)

    def test_stop_is_inside_the_rescued_block(self):
        stop_block = self._stop_block()
        stops = [
            t for t in stop_block["block"]
            if _module(t) == "ansible.builtin.systemd" and t["ansible.builtin.systemd"]["state"] == "stopped"
        ]
        self.assertEqual(len(stops), 1, "the service stop must live inside the rescued block")
        outside = [
            t for t in self.outer
            if _module(t) == "ansible.builtin.systemd" and t["ansible.builtin.systemd"].get("state") == "stopped"
        ]
        self.assertEqual(outside, [], "a stop outside the rescued block has no restart path")

    def test_rescue_restarts_then_fails(self):
        rescue = self._stop_block().get("rescue", [])
        self.assertGreaterEqual(len(rescue), 2, "rescue must restart and then fail")
        self.assertEqual(_module(rescue[0]), "ansible.builtin.systemd")
        self.assertEqual(rescue[0]["ansible.builtin.systemd"]["state"], "started")
        self.assertEqual(
            rescue[0]["ansible.builtin.systemd"]["name"], "{{ cribl_stream_service_name }}"
        )
        self.assertEqual(_module(rescue[-1]), "ansible.builtin.fail", "a rescued upgrade must still fail the run")


if __name__ == "__main__":
    unittest.main()
