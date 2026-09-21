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
RUNNER = ROOT / "roles" / "github_runner"
BASE_IMAGE = "geerlingguy/docker-debian12-ansible:latest"


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

    def test_docker_vms_gather_the_facts_the_netplan_override_needs(self):
        # The netplan override is templated from facts (the VM's own default
        # interface and gateway); a play with gather_facts: false only has
        # them when a task explicitly gathers them.
        play = _play("Configure Docker registry mirror on docker hosts")
        self.assertFalse(play.get("gather_facts", True))
        tasks = list(_tasks(play))
        gather = next(t for t in tasks if t["name"] == "Gather the default route")
        self.assertIn("docker_vms", str(gather["when"]))
        self.assertIn(
            "ansible_default_ipv4", gather["ansible.builtin.setup"]["filter"]
        )
        remove_task = next(
            t for t in tasks if t["name"] == "Remove the hand-placed resolver override"
        )
        self.assertEqual(remove_task["ansible.builtin.file"]["path"], "/etc/netplan/60-dns-interim.yaml")
        self.assertEqual(remove_task["ansible.builtin.file"]["state"], "absent")
        override_task = next(
            t for t in tasks if t["name"] == "Configure the estate resolver on docker VMs"
        )
        self.assertIn("docker_vms", str(override_task["when"]))
        dest = override_task["ansible.builtin.copy"]["dest"]
        dest_basename = dest.rsplit("/", 1)[-1]
        # Netplan concatenates nameserver lists across files in lexical
        # order; this file's address is only tried first if its name sorts
        # before the cloud-init file's.
        self.assertEqual(sorted([dest_basename, "50-cloud-init.yaml"])[0], dest_basename)
        self.assertEqual(override_task["ansible.builtin.copy"]["mode"], "0600")
        flush = next(
            t for t in tasks if t["name"] == "Apply any pending netplan/resolver changes before the probe"
        )
        self.assertEqual(flush["ansible.builtin.meta"], "flush_handlers")
        probe = next(
            t for t in tasks if t["name"] == "Verify a guest name resolves through the new resolver"
        )
        self.assertIn("apt_cacher_group", str(probe["when"]))
        self.assertIs(probe.get("changed_when"), False)
        self.assertIn("getent hosts", probe["ansible.builtin.command"]["cmd"])

    def test_the_netplan_override_renders_the_interface_gateway_and_domain(self):
        # A real Templar render of the ACTUAL override content, not a
        # reimplementation of it.
        play = _play("Configure Docker registry mirror on docker hosts")
        task = next(
            t for t in _tasks(play) if t["name"] == "Configure the estate resolver on docker VMs"
        )
        content_expr = trust_as_template(task["ansible.builtin.copy"]["content"])
        variables = _mark_templates(
            {
                "ansible_default_ipv4": {"interface": "eth0", "gateway": "10.20.0.1"},
                "tofu_data": {"domain": "example.com"},
            }
        )
        templar = Templar(loader=DataLoader(), variables=variables)
        rendered = templar.template(content_expr)
        parsed = yaml.safe_load(rendered)
        iface = parsed["network"]["ethernets"]["eth0"]
        self.assertEqual(iface["nameservers"]["addresses"], ["10.20.0.1"])
        self.assertEqual(iface["nameservers"]["search"], ["example.com"])

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
        self.assertIn("tofu_data.domain", defaults["github_runner_apt_proxy_url"])
        self.assertNotIn("ingress_domain", defaults["github_runner_apt_proxy_url"])
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
        main_tasks = list(_tasks(yaml.safe_load((RUNNER / "tasks" / "main.yml").read_text())))
        include = next(
            t for t in main_tasks if t["name"] == "Retire the former per-host Molecule image build units"
        )
        self.assertEqual(include["ansible.builtin.include_tasks"], "retire_molecule_image_build.yml")

        tasks = list(
            _tasks(yaml.safe_load((RUNNER / "tasks" / "retire_molecule_image_build.yml").read_text()))
        )
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
