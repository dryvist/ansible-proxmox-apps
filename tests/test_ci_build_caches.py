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
  * Every Molecule scenario runs on the pre-built base image the runner host
    builds (falling back to the upstream base off a runner), waits for the
    instance to finish booting before any other module runs, and includes the
    shared apt-proxy task; no scenario builds an image of its own.
  * The runner env template hands APT_PROXY_URL and MOLECULE_BASE_IMAGE to
    the jobs, and the role builds the image from the shared Dockerfile.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "playbooks" / "site" / "01-baseline-infra.yml"
MOLECULE = ROOT / "molecule"
SHARED_TASK = "../resources/tasks/apt_proxy.yml"
BOOT_WAIT = "../resources/tasks/wait_for_boot.yml"
DOCKERFILE = MOLECULE / "resources" / "Dockerfile"
RUNNER = ROOT / "roles" / "github_runner"
BASE_IMAGE = "${MOLECULE_BASE_IMAGE:-geerlingguy/docker-debian12-ansible:latest}"


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
        self.assertNotIn("container_ip", str(task["vars"]))
        self.assertIn("groups['registry_group']", str(task["when"]))

    def test_every_scenario_runs_on_the_prebuilt_image(self):
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

    def test_the_shared_dockerfile_writes_apt_config_not_http_proxy(self):
        lines = DOCKERFILE.read_text().splitlines()
        directives = "\n".join(line for line in lines if not line.startswith("#"))
        self.assertIn("Acquire::http::Proxy", directives)
        self.assertNotIn("http_proxy", directives)

    def test_https_repositories_bypass_the_cache(self):
        # apt's https method inherits the http proxy when its own is unset, and
        # the cache does not tunnel TLS -- an https repository would then be
        # skipped silently. Both writers must pin https to DIRECT.
        for path in (
            DOCKERFILE,
            MOLECULE / "resources" / "tasks" / "apt_proxy.yml",
        ):
            with self.subTest(path=path.name):
                self.assertIn('Acquire::https::Proxy "DIRECT";', path.read_text())

    def test_the_runner_env_hands_the_cache_to_jobs(self):
        env = (ROOT / "roles" / "github_runner" / "templates" / "runner.env.j2").read_text()
        self.assertIn("APT_PROXY_URL={{ github_runner_apt_proxy_url }}", env)
        defaults = yaml.safe_load(
            (ROOT / "roles" / "github_runner" / "defaults" / "main.yml").read_text()
        )
        self.assertIn("ingress_domain", defaults["github_runner_apt_proxy_url"])
        self.assertIn("apt_cacher_group", defaults["github_runner_apt_proxy_url"])
        self.assertIn("MOLECULE_BASE_IMAGE={{ github_runner_molecule_image }}", env)

    def test_the_runner_role_builds_the_image_from_the_shared_dockerfile(self):
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "molecule_image.yml").read_text())))
        deploy = next(t for t in tasks if t["name"] == "Deploy the Molecule base image Dockerfile")
        self.assertEqual(
            deploy["ansible.builtin.copy"]["src"], "{{ role_path }}/../../molecule/resources/Dockerfile"
        )
        self.assertEqual(deploy["notify"], "Build the Molecule base image")
        unit = (RUNNER / "templates" / "molecule-image.service.j2").read_text()
        self.assertIn("--build-arg APT_PROXY_URL={{ github_runner_apt_proxy_url }}", unit)
        self.assertIn("--tag {{ github_runner_molecule_image }}", unit)
        self.assertIn("ARG APT_PROXY_URL", DOCKERFILE.read_text())

    def test_the_first_build_blocks_before_runners_start(self):
        # main.yml enables the pooled runners (which can be handed a job
        # within seconds) right after this include_tasks. A fire-and-forget
        # (no_block: true) first build races that: a job can land before a
        # cold multi-minute build finishes, and Molecule's docker driver then
        # tries to pull a tag that has never existed on the daemon.
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "molecule_image.yml").read_text())))
        build = next(t for t in tasks if t["name"] == "Build the Molecule base image when it is missing")
        self.assertNotIn("no_block", build["ansible.builtin.systemd"])


if __name__ == "__main__":
    unittest.main()
