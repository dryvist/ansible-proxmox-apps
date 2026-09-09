#!/usr/bin/env python3
"""The apt proxy autodetect hook must survive a busy cache, and say when it gives up.

The hook runs on every apt invocation on every guest. It probed each cache
instance once with a short TCP connect and printed DIRECT if none answered.

Two problems, both observed in a fleet converge where six guests failed
`apt` with "Failed to update apt cache after 5 retries:" and NOTHING after
the colon:

  1. A single short connect test is decided by whatever the cache is doing at
     that instant. During a converge it is serving every other guest at once,
     so one timeout demotes a healthy cache.
  2. DIRECT is not a safe fallback everywhere. Some VLANs permit outbound 443
     and the internal network but BLOCK outbound 80, and Debian's default
     sources are http -- so on those guests the fallback is a path that cannot
     work, and apt reports it with an empty reason.

The fallback is deliberately KEPT, because other VLANs do reach upstream. What
changed is that the probe is retried and the give-up is recorded, so the empty
apt failure has a companion line naming what was probed.

This test renders the script the play actually deploys and checks it is valid
shell -- the script is an inline Jinja-templated heredoc, so a rendering
mistake ships silently and only surfaces as apt breaking on every guest.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

PLAY = Path(__file__).resolve().parent.parent / "playbooks" / "site" / "01-baseline-infra.yml"
TASK = "Deploy apt proxy autodetect script"

# Enough total probing to outlast a cache busy serving a converge fan-out,
# while still bounded -- apt may invoke the hook more than once per run.
MIN_TOTAL_PROBE_SECONDS = 6


def _tasks(node):
    if isinstance(node, list):
        for entry in node:
            yield from _tasks(entry)
    elif isinstance(node, dict):
        if "name" in node:
            yield node
        for key in ("tasks", "block", "rescue", "always", "pre_tasks", "post_tasks"):
            if key in node:
                yield from _tasks(node[key])


class AptProxyDetect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        task = next(
            (t for t in _tasks(yaml.safe_load(PLAY.read_text())) if t["name"] == TASK),
            None,
        )
        assert task is not None, f"{TASK!r} not found in {PLAY}"
        template = task["ansible.builtin.copy"]["content"]
        cls.script = Environment().from_string(template).render(
            groups={"apt_cacher_group": ["cache-b", "cache-a"]},
            tofu_data={"domain": "example.invalid"},
            _apt_cache_port="3142",
        )

    def test_the_rendered_script_is_valid_shell(self):
        with tempfile.NamedTemporaryFile("w", suffix=".sh") as handle:
            handle.write(self.script)
            handle.flush()
            result = subprocess.run(["bash", "-n", handle.name],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_declared_instance_is_probed_in_a_stable_order(self):
        # Sorted, so two guests do not disagree about which cache is "first".
        self.assertLess(self.script.index("cache-a.example.invalid"),
                        self.script.index("cache-b.example.invalid"))

    def test_the_probe_is_retried(self):
        self.assertIn("for attempt in", self.script)
        timeouts = [int(word) for line in self.script.splitlines()
                    if "timeout " in line and "/dev/tcp/" in line
                    for word in line.split() if word.isdigit()]
        self.assertTrue(timeouts, "no connect timeout found")
        attempts = self.script.count("1 2 3") and 3
        self.assertGreaterEqual(min(timeouts) * attempts, MIN_TOTAL_PROBE_SECONDS)

    def test_giving_up_is_recorded(self):
        # apt's own failure carries an EMPTY reason, so the only way anyone
        # learns the cache was skipped is if the hook says so itself.
        self.assertIn("logger", self.script)
        self.assertIn("DIRECT", self.script.rsplit("logger", 1)[1])

    def test_the_fallback_is_still_direct(self):
        # Deliberate: VLANs that reach upstream must keep working. This asserts
        # the change did not quietly turn a fallback into a hard failure.
        self.assertEqual(self.script.strip().splitlines()[-1].strip(), "echo DIRECT")


if __name__ == "__main__":
    unittest.main()
