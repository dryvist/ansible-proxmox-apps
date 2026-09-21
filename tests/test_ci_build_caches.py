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

import json
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "playbooks" / "site" / "01-baseline-infra.yml"
# The Docker daemon play (registry mirror, storage driver, DNS) lives in its
# own file, split out of SITE once the DNS block grew SITE past the site/
# token-limit gate.
DOCKER_DAEMON_SITE = ROOT / "playbooks" / "site" / "01a-docker-daemon.yml"
MOLECULE = ROOT / "molecule"
SHARED_TASK = "../resources/tasks/apt_proxy.yml"
BOOT_WAIT = "../resources/tasks/wait_for_boot.yml"
DOCKERFILE = MOLECULE / "resources" / "Dockerfile"
RUNNER = ROOT / "roles" / "github_runner"
BASE_IMAGE = "${MOLECULE_BASE_IMAGE:-geerlingguy/docker-debian12-ansible:latest}"


def _play(name):
    for path in (SITE, DOCKER_DAEMON_SITE):
        for play in yaml.safe_load(path.read_text()):
            if play.get("name") == name:
                return play
    raise AssertionError(f"play {name!r} not found in {SITE} or {DOCKER_DAEMON_SITE}")


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


def _mark_templates(value):
    """Recursively mark every string in a loaded YAML structure as a trusted
    template, matching how Ansible treats values sourced from a play/task."""
    if isinstance(value, str):
        return trust_as_template(value)
    if isinstance(value, dict):
        return {k: _mark_templates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mark_templates(v) for v in value]
    return value


class CiBuildCaches(unittest.TestCase):
    def test_both_cache_plays_reach_the_docker_vms(self):
        for name in (
            "Configure Docker registry mirror on docker hosts",
            "Configure apt proxy on LXC containers and docker VMs",
        ):
            with self.subTest(play=name):
                self.assertIn("docker_vms", _play(name)["hosts"])

    def test_the_mirror_is_addressed_by_the_estate_domain(self):
        # Guest names resolve under the estate domain; the ingress subdomain
        # carries only ingress vhosts. tofu_data.domain matches the apt
        # Proxy-Auto-Detect hook, which addresses its own guest the same way.
        play = _play("Configure Docker registry mirror on docker hosts")
        task = next(t for t in _tasks(play) if t["name"] == "Configure Docker registry mirror")
        host = task["vars"]["_registry_host"]
        self.assertIn("tofu_data.domain", host)
        self.assertNotIn("ingress_domain", host)
        self.assertNotIn("container_ip", host)
        self.assertIn("groups['registry_group']", str(task["when"]))

    def test_the_mirror_host_and_apt_proxy_url_render_under_the_estate_domain(self):
        # A real Templar render of the ACTUAL expressions, not a
        # reimplementation of them: with ingress_domain and tofu_data.domain
        # set to two DIFFERENT values, each URL must land on the estate
        # domain, never the ingress one -- the bug this guards was a guest
        # name built from the wrong one, which resolves to nothing.
        play = _play("Configure Docker registry mirror on docker hosts")
        task = next(t for t in _tasks(play) if t["name"] == "Configure Docker registry mirror")
        registry_host_expr = trust_as_template(task["vars"]["_registry_host"])
        apt_proxy_defaults = yaml.safe_load(
            (RUNNER / "defaults" / "main.yml").read_text()
        )
        apt_proxy_expr = trust_as_template(apt_proxy_defaults["github_runner_apt_proxy_url"])
        variables = _mark_templates(
            {
                "groups": {"registry_group": ["registry-1"], "apt_cacher_group": ["apt-cache-1"]},
                "ingress_domain": "pve.example.com",
                "tofu_data": {"domain": "example.com", "constants": {"service_ports": {}}},
            }
        )
        templar = Templar(loader=DataLoader(), variables=variables)
        registry_host = templar.template(registry_host_expr)
        apt_proxy_url = templar.template(apt_proxy_expr)
        self.assertTrue(registry_host.endswith(".example.com"), registry_host)
        self.assertNotIn("pve.", registry_host)
        self.assertTrue(apt_proxy_url.startswith("http://apt-cache-1.example.com:"), apt_proxy_url)
        self.assertNotIn("pve.", apt_proxy_url)

    def test_daemon_json_content_renders_as_valid_json_with_one_newline(self):
        # A real render of the WHOLE content: expression, not a
        # reimplementation -- a `>-` folded scalar with a trailing
        # `{{ "\n" }}` renders the two characters backslash-n literally
        # instead of a real newline, which is invalid JSON and leaves dockerd
        # refusing to start. json.loads() and an exact-newline check catch
        # that the string-matching tests above cannot.
        play = _play("Configure Docker registry mirror on docker hosts")
        task = next(t for t in _tasks(play) if t["name"] == "Configure Docker registry mirror")
        content_expr = task["ansible.builtin.copy"]["content"]
        fixture = {
            "groups": {"registry_group": ["registry-1"]},
            "hostvars": {
                "registry-1": {},
                "localhost": {"tofu_data": {"constants": {"service_ports": {"registry": 5000}}}},
            },
            "tofu_data": {"domain": "example.com"},
            "ansible_virtualization_type": "kvm",
            "host_tags": ["docker"],
        }
        variables = {**fixture, **task["vars"]}
        templar = Templar(loader=DataLoader(), variables=_mark_templates(variables))
        rendered = templar.template(trust_as_template(content_expr))
        self.assertTrue(rendered.endswith("\n"))
        self.assertFalse(rendered.endswith("\n\n"))
        self.assertNotIn("\\n", rendered)
        parsed = json.loads(rendered)  # raises if the daemon.json this writes is invalid
        # Containers inherit the host's own upstream resolvers by default
        # (dockerd's documented behavior); the daemon config does not pin a
        # resolver.
        self.assertNotIn("dns", parsed)

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
        self.assertIn("tofu_data.domain", defaults["github_runner_apt_proxy_url"])
        self.assertNotIn("ingress_domain", defaults["github_runner_apt_proxy_url"])
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
        build = next(t for t in tasks if t["name"] == "Start the Molecule base image build")
        self.assertNotIn("no_block", build["ansible.builtin.systemd"])

    def test_a_failed_first_build_surfaces_its_own_journal(self):
        # This host ships no logs to the central platform (Vikunja 3353) and
        # SSH is off-limits, so a bare systemd failure here is a dead end --
        # a converge failure with no way to see why. The rescue reads the
        # unit's own journal and fails WITH it.
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "molecule_image.yml").read_text())))
        outer = next(t for t in tasks if t["name"] == "Build the Molecule base image when it is missing")
        self.assertIn("block", outer)
        self.assertIn("rescue", outer)
        rescue_names = [t["name"] for t in outer["rescue"]]
        self.assertIn("Read the failed build's journal", rescue_names)
        journal_task = next(t for t in outer["rescue"] if t["name"] == "Read the failed build's journal")
        self.assertIn("journalctl", journal_task["ansible.builtin.command"]["cmd"])
        self.assertIn("github-runner-molecule-image.service", journal_task["ansible.builtin.command"]["cmd"])
        self.assertIs(journal_task.get("changed_when"), False)
        fail_task = next(t for t in outer["rescue"] if t["name"] == "Fail with the build's own output")
        self.assertIn("stdout_lines", fail_task["ansible.builtin.fail"]["msg"])

    def test_a_host_with_no_replicas_does_not_build_the_image(self):
        # A host with github_runner_replicas: 0 runs no scenarios, so it has
        # no consumer for the image and must not build one.
        tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "main.yml").read_text())))
        include = next(t for t in tasks if t["name"] == "Build the Molecule base image every scenario runs on")
        self.assertEqual(include.get("when"), "github_runner_replicas | int > 0")


if __name__ == "__main__":
    unittest.main()
