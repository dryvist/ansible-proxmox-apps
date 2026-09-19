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
  * Every Molecule scenario points apt at APT_PROXY_URL: a prebuilt-image
    scenario includes the shared prepare task, a scenario that builds from the
    shared Dockerfile passes the variable into the build.
  * The runner env template hands APT_PROXY_URL to the jobs.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "playbooks" / "site" / "01-baseline-infra.yml"
MOLECULE = ROOT / "molecule"
SHARED_TASK = "../resources/tasks/apt_proxy.yml"
SHARED_DOCKERFILE = "../resources/Dockerfile.j2"


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

    def test_every_scenario_points_apt_at_the_cache(self):
        scenarios = [d for d in MOLECULE.iterdir() if (d / "molecule.yml").exists()]
        self.assertGreater(len(scenarios), 0)
        for scenario in scenarios:
            with self.subTest(scenario=scenario.name):
                config = yaml.safe_load((scenario / "molecule.yml").read_text())
                builds = [
                    p for p in config.get("platforms", [])
                    if p.get("dockerfile") == SHARED_DOCKERFILE
                ]
                for platform in builds:
                    self.assertEqual(
                        platform.get("env", {}).get("APT_PROXY_URL"), "${APT_PROXY_URL}",
                        f"{scenario.name}: a Dockerfile build must pass APT_PROXY_URL",
                    )
                prepare = scenario / "prepare.yml"
                self.assertTrue(
                    prepare.exists() or builds,
                    f"{scenario.name}: no prepare.yml and no shared Dockerfile build",
                )
                if prepare.exists():
                    includes = [
                        t.get("ansible.builtin.include_tasks")
                        for t in _tasks(yaml.safe_load(prepare.read_text()))
                    ]
                    self.assertIn(SHARED_TASK, includes)

    def test_the_shared_dockerfile_writes_apt_config_not_http_proxy(self):
        lines = (MOLECULE / "resources" / "Dockerfile.j2").read_text().splitlines()
        directives = "\n".join(line for line in lines if not line.startswith("#"))
        self.assertIn("Acquire::http::Proxy", directives)
        self.assertNotIn("http_proxy", directives)

    def test_the_runner_env_hands_the_cache_to_jobs(self):
        env = (ROOT / "roles" / "github_runner" / "templates" / "runner.env.j2").read_text()
        self.assertIn("APT_PROXY_URL={{ github_runner_apt_proxy_url }}", env)
        defaults = yaml.safe_load(
            (ROOT / "roles" / "github_runner" / "defaults" / "main.yml").read_text()
        )
        self.assertIn("ingress_domain", defaults["github_runner_apt_proxy_url"])
        self.assertIn("apt_cacher_group", defaults["github_runner_apt_proxy_url"])


if __name__ == "__main__":
    unittest.main()
