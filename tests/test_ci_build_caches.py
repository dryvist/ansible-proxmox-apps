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
    pulls (falling back to the upstream base off a runner), waits for the
    instance to finish booting before any other module runs, and includes the
    shared apt-proxy task; no scenario builds an image of its own.
  * The runner env template hands APT_PROXY_URL and MOLECULE_BASE_IMAGE to
    the jobs; the image itself is built and published to GHCR by
    .github/workflows/molecule-image.yml, never by a runner host.
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

    def test_the_image_is_published_to_ghcr_not_built_on_a_runner_host(self):
        # The host never builds this image -- roles/github_runner has no
        # molecule_image.yml, no build service/timer template, and no
        # matching handler. .github/workflows/molecule-image.yml is the only
        # thing that builds molecule/resources/Dockerfile.
        self.assertFalse((RUNNER / "tasks" / "molecule_image.yml").exists())
        self.assertFalse((RUNNER / "templates" / "molecule-image.service.j2").exists())
        self.assertFalse((RUNNER / "templates" / "molecule-image.timer.j2").exists())
        handlers = (RUNNER / "handlers" / "main.yml").read_text()
        self.assertNotIn("Build the Molecule base image", handlers)

        defaults = yaml.safe_load((RUNNER / "defaults" / "main.yml").read_text())
        self.assertEqual(defaults["github_runner_molecule_image"], "ghcr.io/dryvist/molecule-debian12:latest")

        workflow = (ROOT / ".github" / "workflows" / "molecule-image.yml").read_text()
        self.assertIn("ghcr.io/dryvist/molecule-debian12", workflow)
        self.assertIn("docker/build-push-action", workflow)

    def test_the_runner_role_pulls_the_published_image(self):
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "main.yml").read_text())))
        pull = next(t for t in tasks if t["name"] == "Pull the Molecule base image every scenario runs on")
        self.assertEqual(pull["community.docker.docker_image"]["name"], "{{ github_runner_molecule_image }}")
        self.assertEqual(pull["community.docker.docker_image"]["source"], "pull")

    def test_a_host_with_no_replicas_does_not_pull_the_image(self):
        # A host with github_runner_replicas: 0 runs no scenarios, so it has
        # no consumer for the image and must not pull one.
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "main.yml").read_text())))
        pull = next(t for t in tasks if t["name"] == "Pull the Molecule base image every scenario runs on")
        self.assertEqual(pull.get("when"), "github_runner_replicas | int > 0")


if __name__ == "__main__":
    unittest.main()
