"""The single Docker daemon renderer keeps storage pins effective."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = ("roles", "playbooks")
SHARED_WRITER = ROOT / "roles" / "docker_engine" / "tasks" / "daemon_json.yml"
ENGINE_DEFAULTS = ROOT / "roles" / "docker_engine" / "defaults" / "main.yml"


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
                if path == SHARED_WRITER:
                    defaults = yaml.safe_load(ENGINE_DEFAULTS.read_text(encoding="utf-8"))
                    config = {
                        **defaults["docker_engine_daemon_json_base"],
                        **defaults["docker_engine_daemon_json_storage"],
                    }
                else:
                    config = None
                yield path, config


class DaemonJsonPinsImageStore(unittest.TestCase):
    def test_every_writer_pins_the_image_store_with_the_driver(self):
        writers = list(_daemon_json_writers())
        self.assertTrue(writers, "no /etc/docker/daemon.json writer was found")
        self.assertEqual([path for path, _config in writers], [SHARED_WRITER])
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
        Splunk) -- see roles/docker_engine/tasks/daemon_json.yml.
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
