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

One writer (playbooks/site/01a-docker-daemon.yml) wraps its ENTIRE content in
one Jinja expression (`content: "{{ (_daemon_json | combine(...)) |
to_nice_json }}\n"`) rather than embedding `{{ vars }}` inside literal JSON
text -- the two writers have genuinely different shapes. The stub-and-parse
approach above silently produced a JSONDecodeError for that writer (an
uncaught exception counts as a subTest failure, so this was not a quiet
pass -- but nothing invokes this file from CI today, so it went unnoticed).
`_daemon_json_writers` falls back to reading that task's own `vars:` dict
structurally in that case: this test only ever asserts on KEY PRESENCE, never
on a rendered value, so the unrendered YAML dict already carries everything
the assertions need.
"""

import json
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = ("roles", "playbooks")
JINJA = re.compile(r"{{.*?}}", re.S)


def _copy_task_nodes(node):
    """Yield every task dict that contains an ansible.builtin.copy key."""
    if isinstance(node, dict):
        if "ansible.builtin.copy" in node:
            yield node
        for value in node.values():
            yield from _copy_task_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _copy_task_nodes(item)


def _config_from_vars(task_vars):
    """Reconstruct the daemon.json shape from a task's own `vars:` dict.

    Only ever used as a fallback (below) for a writer whose `content` is not
    itself parseable JSON once Jinja expressions are stubbed -- i.e. one that
    wraps its ENTIRE content in a single Jinja expression rather than
    embedding `{{ vars }}` inside literal JSON text. Every value read here is
    the raw, unrendered YAML dict Ansible would `combine()` at runtime;
    unrendered leaf strings are fine because this test only asserts on which
    KEYS are present, never on a rendered value.
    """
    if not isinstance(task_vars, dict):
        return None
    combined = {}
    for key, value in task_vars.items():
        if key.startswith("_") and isinstance(value, dict):
            combined.update(value)
    return combined or None


def _daemon_json_writers():
    for directory in SEARCH_DIRS:
        for path in sorted((ROOT / directory).rglob("*.yml")):
            text = path.read_text(encoding="utf-8")
            if "/etc/docker/daemon.json" not in text:
                continue
            for task in _copy_task_nodes(yaml.safe_load(text)):
                copy_args = task["ansible.builtin.copy"]
                if not isinstance(copy_args, dict):
                    continue
                if copy_args.get("dest") != "/etc/docker/daemon.json":
                    continue
                content = copy_args.get("content")
                if not isinstance(content, str):
                    continue
                try:
                    config = json.loads(JINJA.sub("stub", content))
                except json.JSONDecodeError:
                    config = _config_from_vars(task.get("vars"))
                if config is not None:
                    yield path, config


class DaemonJsonPinsImageStore(unittest.TestCase):
    def test_every_writer_pins_the_image_store_with_the_driver(self):
        writers = list(_daemon_json_writers())
        self.assertTrue(writers, "no /etc/docker/daemon.json writer was found")
        for path, config in writers:
            with self.subTest(path=str(path.relative_to(ROOT))):
                if "storage-driver" not in config:
                    continue
                self.assertIs(
                    config.get("features", {}).get("containerd-snapshotter"),
                    False,
                    "pins storage-driver without disabling the containerd "
                    "image store, which makes the pin inert",
                )

    def test_every_writer_sets_journald_with_a_container_name_tag(self):
        """Every container on a docker host must be findable by name.

        Docker's journald driver otherwise tags an entry with the
        container's short ID, which nobody can search on without first
        looking the ID up. log-opts.tag is what makes a container's own
        output findable by name in the journal (and, downstream, in
        Splunk) -- see playbooks/site/01a-docker-daemon.yml.
        """
        writers = list(_daemon_json_writers())
        self.assertTrue(writers, "no /etc/docker/daemon.json writer was found")
        for path, config in writers:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertEqual(
                    config.get("log-driver"),
                    "journald",
                    "does not set the daemon-wide default log driver to "
                    "journald -- a container on this host falls back to "
                    "Docker's json-file default, which nothing on the host "
                    "reads, and its output never reaches Splunk",
                )
                self.assertTrue(
                    config.get("log-opts", {}).get("tag"),
                    "sets log-driver journald but no log-opts.tag -- every "
                    "container's own output is still only findable by its "
                    "short container ID",
                )


if __name__ == "__main__":
    unittest.main()
