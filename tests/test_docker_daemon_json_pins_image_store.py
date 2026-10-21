"""The single Docker daemon renderer keeps storage pins effective."""

import json
from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template


ROOT = Path(__file__).resolve().parents[1]
SEARCH_DIRS = ("roles", "playbooks")
SHARED_WRITER = ROOT / "roles" / "docker_engine" / "tasks" / "daemon_json.yml"
ENGINE_DEFAULTS = ROOT / "roles" / "docker_engine" / "defaults" / "main.yml"


def _daemon_copy_content(task_file):
    tasks = yaml.safe_load(task_file.read_text(encoding="utf-8"))
    task = next(task for task in tasks if task.get("name") == "Configure Docker daemon JSON")
    return task["ansible.builtin.copy"]["content"]


def _mark_templates(value):
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {key: _mark_templates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mark_templates(item) for item in value]
    return value


def _rendered_daemon_config(virtualization_type, task_file):
    defaults = yaml.safe_load(ENGINE_DEFAULTS.read_text(encoding="utf-8"))
    variables = _mark_templates(
        {
            **defaults,
            "groups": {"registry_group": ["registry-1"]},
            "hostvars": {
                "localhost": {"tofu_data": {"constants": {"service_ports": {"registry": 5000}}}}
            },
            "tofu_data": {"domain": "example.com"},
            "ansible_facts": {"virtualization_type": virtualization_type},
        }
    )
    return Templar(loader=DataLoader(), variables=variables).template(
        trust_as_template(_daemon_copy_content(task_file))
    )


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
    def test_site_and_first_install_render_the_same_lxc_and_vm_config(self):
        site = yaml.safe_load(
            (ROOT / "playbooks" / "site" / "01a-docker-daemon.yml").read_text(
                encoding="utf-8"
            )
        )[0]
        site_call = next(
            task for task in site["tasks"]
            if task.get("name") == "Configure Docker daemon on installed Docker hosts"
        )
        install_tasks = yaml.safe_load(
            (ROOT / "roles" / "docker_engine" / "tasks" / "main.yml").read_text(
                encoding="utf-8"
            )
        )
        install_call = next(
            task for task in install_tasks
            if task.get("name") == "Configure the Docker daemon before installing Docker packages"
        )
        self.assertEqual(site_call["ansible.builtin.include_role"]["name"], "docker_engine")
        site_task_file = (
            ROOT
            / "roles"
            / site_call["ansible.builtin.include_role"]["name"]
            / "tasks"
            / site_call["ansible.builtin.include_role"]["tasks_from"]
        )
        install_task_file = ROOT / "roles" / "docker_engine" / "tasks" / install_call[
            "ansible.builtin.import_tasks"
        ]
        self.assertEqual(site_task_file, install_task_file)

        for kind, expect_storage in (("lxc", True), ("kvm", False)):
            with self.subTest(virtualization_type=kind):
                rendered = _rendered_daemon_config(kind, site_task_file)
                installed_rendered = _rendered_daemon_config(kind, install_task_file)
                self.assertEqual(rendered, installed_rendered)
                config = json.loads(rendered)
                self.assertTrue(rendered.endswith("\n"))
                self.assertEqual(config["registry-mirrors"], ["http://registry-1.example.com:5000"])
                self.assertEqual(config["insecure-registries"], ["registry-1.example.com:5000"])
                self.assertEqual(config["log-driver"], "journald")
                self.assertEqual(config["log-opts"]["tag"], "{{.Name}}")
                if expect_storage:
                    self.assertEqual(config["storage-driver"], "fuse-overlayfs")
                    self.assertIs(config["features"]["containerd-snapshotter"], False)
                else:
                    self.assertNotIn("storage-driver", config)
                    self.assertNotIn("features", config)

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
