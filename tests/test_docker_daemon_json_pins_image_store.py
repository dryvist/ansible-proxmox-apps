"""A pinned Docker storage driver must be written with the legacy image store.

The containerd image store replaces the graph-driver stack, so with it enabled
`storage-driver` is parsed and then has no effect. A file that pins a driver
and says nothing about the image store therefore reads as a decision that is
not in force. On the Docker guests that means fuse-overlayfs, which the ZFS-backed
containers need, is asked for and not used.

Every writer under roles and playbooks is checked, so a new one cannot
reintroduce the gap. The Molecule scenarios are out of scope: their instances
give the inner daemon a volume for its layer root, so the driver it ends up on
is a real filesystem either way. Jinja expressions are stubbed before parsing
-- the assertion is about the JSON shape, not about any rendered value.
"""

import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = ("roles", "playbooks")
JINJA = re.compile(r"{{.*?}}", re.S)


def _copy_tasks(node):
    """Yield every ansible.builtin.copy task in a parsed YAML document."""
    if isinstance(node, dict):
        if "ansible.builtin.copy" in node:
            yield node["ansible.builtin.copy"]
        for value in node.values():
            yield from _copy_tasks(value)
    elif isinstance(node, list):
        for item in node:
            yield from _copy_tasks(item)


def _daemon_json_writers():
    for directory in SEARCH_DIRS:
        for path in sorted((ROOT / directory).rglob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if "/etc/docker/daemon.json" not in text:
                continue
            for task in _copy_tasks(yaml.safe_load(text)):
                if not isinstance(task, dict):
                    continue
                if task.get("dest") != "/etc/docker/daemon.json":
                    continue
                content = task.get("content")
                if isinstance(content, str):
                    yield path, content


class DaemonJsonPinsImageStore(unittest.TestCase):
    def test_every_writer_pins_the_image_store_with_the_driver(self):
        writers = list(_daemon_json_writers())
        self.assertTrue(writers, "no /etc/docker/daemon.json writer was found")
        for path, content in writers:
            with self.subTest(path=str(path.relative_to(ROOT))):
                config = json.loads(JINJA.sub("stub", content))
                if "storage-driver" not in config:
                    continue
                self.assertIs(
                    config.get("features", {}).get("containerd-snapshotter"),
                    False,
                    "pins storage-driver without disabling the containerd "
                    "image store, which makes the pin inert",
                )


if __name__ == "__main__":
    unittest.main()
