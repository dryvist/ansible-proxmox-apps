#!/usr/bin/env python3
"""The CI build caches must reach every consumer, by name.

Two caches serve the Molecule matrix: the registry mirror (every image the
runner hosts' daemons pull) and the apt cache (every package a test container
installs). Each is wired at exactly one place per consumer, and a scenario
that misses the wiring silently pays the cold-download minutes the caches
exist to remove -- so the wiring is asserted structurally here.

  * The registry-mirror and apt-proxy plays in site.yml target the docker VMs
    (the runner hosts), not only the LXC containers.
  * The mirror is addressed by FQDN under the ingress zone; a container_ip
    lookup would put an address in a daemon config (docs/IP_AUTHORITY.md).
  * Every Molecule scenario runs on the upstream geerlingguy/docker-debian12-
    ansible image, waits for the instance to finish booting before any other
    module runs, and includes the shared apt-proxy task; no scenario builds
    or pre-bakes an image of its own -- a role that needs Docker Engine gets
    it from its own docker_engine meta dependency at converge, through the
    same apt cache.
  * The runner env template hands APT_PROXY_URL to the jobs; there is no
    Molecule-image variable to hand alongside it.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "playbooks" / "site" / "01-baseline-infra.yml"
MOLECULE = ROOT / "molecule"
SHARED_TASK = "../resources/tasks/apt_proxy.yml"
BOOT_WAIT = "../resources/tasks/wait_for_boot.yml"
RUNNER = ROOT / "roles" / "github_runner"
BASE_IMAGE = "geerlingguy/docker-debian12-ansible:latest"


def _play(name):
    for play in yaml.safe_load(SITE.read_text()):
        if play.get("name") == name:
            return play
    raise AssertionError(f"play {name!r} not found in {SITE}")


def _tasks(node):
    if isinstance(node, list):
        for entry in node:
            yield from _tasks(entry)
    elif isinstance(node, dict):
        if "name" in node and "hosts" not in node:
            yield node
        for key in ("tasks", "block", "rescue", "always", "pre_tasks", "post_tasks"):
            if key in node:
                yield from _tasks(node[key])


class CiBuildCaches(unittest.TestCase):
    def test_both_cache_plays_reach_the_docker_vms(self):
        for name in (
            "Configure Docker registry mirror on docker hosts",
            "Configure apt proxy on LXC containers and docker VMs",
        ):
            with self.subTest(play=name):
                self.assertIn("docker_vms", _play(name)["hosts"])

    def test_the_mirror_is_addressed_by_ingress_fqdn(self):
        play = _play("Configure Docker registry mirror on docker hosts")
        task = next(t for t in _tasks(play) if t["name"] == "Configure Docker registry mirror")
        host = task["vars"]["_registry_host"]
        self.assertIn("ingress_domain", host)
        # container_ip is legitimate here for _dns_servers only: a DNS
        # resolver cannot be addressed by a name it would itself have to
        # resolve, the same static-anchor exception docs/IP_AUTHORITY.md
        # already documents for technitium_dns. _registry_host stays FQDN.
        self.assertNotIn("container_ip", host)
        self.assertIn("groups['registry_group']", str(task["when"]))

    def test_dns_servers_come_from_the_technitium_group_not_a_literal(self):
        play = _play("Configure Docker registry mirror on docker hosts")
        task = next(t for t in _tasks(play) if t["name"] == "Configure Docker registry mirror")
        dns_servers = task["vars"]["_dns_servers"]
        self.assertIn("groups['technitium_dns_group']", dns_servers)
        self.assertNotRegex(dns_servers, r"\b\d{1,3}(\.\d{1,3}){3}\b")

    def test_every_scenario_runs_on_the_upstream_image(self):
        scenarios = [d for d in MOLECULE.iterdir() if (d / "molecule.yml").exists()]
        self.assertGreater(len(scenarios), 0)
        for scenario in scenarios:
            with self.subTest(scenario=scenario.name):
                config = yaml.safe_load((scenario / "molecule.yml").read_text())
                for platform in config["platforms"]:
                    self.assertEqual(platform.get("image"), BASE_IMAGE, platform["name"])
                    self.assertTrue(platform.get("pre_build_image"), platform["name"])
                    self.assertNotIn("dockerfile", platform, platform["name"])
                tasks = list(_tasks(yaml.safe_load((scenario / "prepare.yml").read_text())))
                includes = [t.get("ansible.builtin.include_tasks") for t in tasks]
                self.assertIn(SHARED_TASK, includes)
                # The boot wait is the first thing after the connection wait:
                # any module that runs before it can lose its /tmp payload.
                connected = next(i for i, t in enumerate(tasks) if "ansible.builtin.wait_for_connection" in t)
                self.assertEqual(includes[connected + 1], BOOT_WAIT, scenario.name)

    def test_https_repositories_bypass_the_cache(self):
        # apt's https method inherits the http proxy when its own is unset, and
        # the cache does not tunnel TLS -- an https repository would then be
        # skipped silently.
        path = MOLECULE / "resources" / "tasks" / "apt_proxy.yml"
        self.assertIn('Acquire::https::Proxy "DIRECT";', path.read_text())

    def test_the_runner_env_hands_the_cache_to_jobs(self):
        env = (ROOT / "roles" / "github_runner" / "templates" / "runner.env.j2").read_text()
        self.assertIn("APT_PROXY_URL={{ github_runner_apt_proxy_url }}", env)
        defaults = yaml.safe_load(
            (ROOT / "roles" / "github_runner" / "defaults" / "main.yml").read_text()
        )
        self.assertIn("ingress_domain", defaults["github_runner_apt_proxy_url"])
        self.assertIn("apt_cacher_group", defaults["github_runner_apt_proxy_url"])
        # No Molecule-image variable to hand alongside it -- every scenario
        # names the upstream image directly.
        self.assertNotIn("MOLECULE_BASE_IMAGE", env)

    def test_no_molecule_image_is_built_or_overridden_on_a_runner_host(self):
        # The host never builds or pulls a Molecule image -- there is nothing
        # to build (molecule_image.yml, the build service/timer templates, the
        # matching handler, and every github_runner_molecule_image* variable
        # are all gone) and no MOLECULE_BASE_IMAGE override to hand a job.
        self.assertFalse((RUNNER / "tasks" / "molecule_image.yml").exists())
        self.assertFalse((RUNNER / "templates" / "molecule-image.service.j2").exists())
        self.assertFalse((RUNNER / "templates" / "molecule-image.timer.j2").exists())
        self.assertFalse((MOLECULE / "resources" / "Dockerfile").exists())
        handlers = (RUNNER / "handlers" / "main.yml").read_text()
        self.assertNotIn("Build the Molecule base image", handlers)
        main_tasks = (RUNNER / "tasks" / "main.yml").read_text()
        self.assertNotIn("include_tasks: molecule_image.yml", main_tasks)
        self.assertNotIn("Build the Molecule base image every scenario runs on", main_tasks)
        defaults = (RUNNER / "defaults" / "main.yml").read_text()
        self.assertNotIn("github_runner_molecule_image", defaults)

    def test_the_role_retires_the_old_molecule_image_build_units(self):
        # The role must remove github-runner-molecule-image.{service,timer}
        # where present, not just stop deploying them, or an enabled timer
        # keeps firing a build nothing consumes.
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "main.yml").read_text())))
        removed = next(
            t for t in tasks if t["name"] == "Remove the old Molecule image build unit files and Dockerfile context"
        )
        self.assertEqual(
            set(removed["loop"]),
            {
                "/etc/systemd/system/github-runner-molecule-image.timer",
                "/etc/systemd/system/github-runner-molecule-image.service",
                "/etc/github-runner/molecule-image",
            },
        )
        for unit_name in ("github-runner-molecule-image.timer", "github-runner-molecule-image.service"):
            with self.subTest(unit=unit_name):
                stopped = next(
                    t
                    for t in tasks
                    if t.get("ansible.builtin.systemd", {}).get("name") == unit_name
                    and t["ansible.builtin.systemd"].get("state") == "stopped"
                )
                self.assertFalse(stopped["ansible.builtin.systemd"]["enabled"])


if __name__ == "__main__":
    unittest.main()
