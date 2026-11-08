"""OpenHands skeleton contract: tag-mapped inventory group, isolated site
play, ZCode Web gate for the group, and a role that never reads OpenBao
secret facts."""

from pathlib import Path
import re
import unittest

import yaml

from app_agent_helpers import _task


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "openhands"
MAPPING = ROOT / "inventory" / "load_tofu" / "add_splunk_and_docker_hosts.yml"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "openhands_host.yml"
SITE = ROOT / "playbooks" / "site" / "03-notifications-and-core-apps.yml"

# One `+ (['group'] if 'tag' in (item.value.tags | default([])) else [])` term
# of the docker-VM groups expression.
TAG_GROUP_TERM = re.compile(
    r"\(\['(?P<group>[a-z_]+)'\]\s+"
    r"if\s+'(?P<tag>[a-z0-9-]+)'\s+"
    r"in\s+\(item\.value\.tags\s+\|\s+default\(\[\]\)\)\s+"
    r"else\s+\[\]\)"
)


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _docker_vm_groups_expression():
    task = _task(_load(MAPPING), "Add Docker VMs to inventory (SSH connection — testing/dev only)")
    return task["ansible.builtin.add_host"]["groups"]


class OpenHandsInventoryContract(unittest.TestCase):
    def test_openhands_tag_yields_openhands_host(self):
        pairs = {
            match["tag"]: match["group"]
            for match in TAG_GROUP_TERM.finditer(_docker_vm_groups_expression())
        }
        self.assertEqual(pairs.get("openhands"), "openhands_host")
        self.assertEqual(pairs.get("agent-sandbox"), "agent_sandbox_host")

    def test_group_vars_turn_zcode_web_off_and_leave_other_gates_at_defaults(self):
        group_vars = _load(GROUP_VARS)
        self.assertIs(group_vars["agent_sandbox_zcode_web_enabled"], False)
        # The dispatcher and ci-resolver stay at their false role defaults:
        # the group file must not override them.
        self.assertNotIn("agent_sandbox_dispatch_access_enabled", group_vars)
        self.assertNotIn("agent_sandbox_dispatch_user", group_vars)
        self.assertNotIn("agent_sandbox_ci_resolver_enabled", group_vars)
        sandbox_defaults = (
            (ROOT / "roles" / "agent_sandbox" / "defaults" / "main" / "00-runtime.yml").read_text()
        )
        self.assertIn("agent_sandbox_dispatch_access_enabled: false", sandbox_defaults)
        ci_resolver_defaults = (
            (ROOT / "roles" / "agent_sandbox" / "defaults" / "main" / "10-ci-resolver.yml").read_text()
        )
        self.assertIn("agent_sandbox_ci_resolver_enabled: false", ci_resolver_defaults)

    def test_zcode_web_content_sits_entirely_inside_the_flag_gate(self):
        # With the flag off the rendered project must carry no zcode-web
        # service and therefore no credential-file mount and no published
        # port; prove every such line lives inside the gated region.
        compose = (ROOT / "roles" / "agent_sandbox" / "templates" / "docker-compose.yml.j2").read_text()
        marker = "{% if agent_sandbox_zcode_web_enabled | bool %}"
        gate = compose[compose.index(marker):compose.rindex("{% endif %}")]
        outside = compose.replace(gate, "")
        for gated in (
            "zcode-web:",
            "agent_sandbox_zcode_web_env_file",
            "agent_sandbox_zcode_web_host_port",
        ):
            self.assertIn(gated, gate)
            self.assertNotIn(gated, outside)


class OpenHandsPlayContract(unittest.TestCase):
    def _play(self):
        plays = _load(SITE)
        play = next(play for play in plays if play.get("hosts") == "openhands_host")
        sandbox_index = next(
            index for index, play in enumerate(plays) if play.get("hosts") == "agent_sandbox_host"
        )
        return plays, play, sandbox_index

    def test_play_follows_the_agent_sandbox_play_in_isolated_shape(self):
        plays, play, sandbox_index = self._play()
        self.assertEqual(play["name"], "Deploy OpenHands")
        self.assertEqual(plays.index(play), sandbox_index + 1)
        self.assertEqual(play["tags"], ["openhands"])
        self.assertIs(play["gather_facts"], False)
        self.assertIs(play["become"], True)

        block_task = _task(play["tasks"], "Converge openhands (isolated — failure does not abort downstream plays)")
        self.assertEqual(block_task["tags"], ["openhands"])
        gather = _task(block_task["block"], "Gather host facts")
        self.assertEqual(gather["ansible.builtin.include_tasks"]["file"], "../tasks/gather.yml")
        include = _task(block_task["block"], "Include openhands role")
        self.assertEqual(include["ansible.builtin.include_role"]["name"], "openhands")
        self.assertEqual(include["ansible.builtin.include_role"]["apply"]["tags"], ["openhands"])

        rescue = _task(block_task["rescue"], "Record isolated failure and continue")
        self.assertEqual(
            rescue["ansible.builtin.include_tasks"], "../tasks/record_isolated_failure.yml"
        )
        self.assertEqual(rescue["vars"]["_isolated_play_name"], "openhands")


class OpenHandsRoleContract(unittest.TestCase):
    def test_defaults_pin_versions_port_state_dir_and_conversation_limits(self):
        defaults = _load(ROLE / "defaults" / "main.yml")
        self.assertEqual(defaults["openhands_canvas_version"], "1.34.0")
        self.assertEqual(defaults["openhands_agent_server_version"], "1.58.1")
        self.assertEqual(defaults["openhands_automation_version"], "1.26.0")
        self.assertEqual(defaults["openhands_port"], 443)
        self.assertIs(defaults["openhands_service_enabled"], False)
        self.assertEqual(defaults["openhands_user"], "openhands")
        self.assertEqual(defaults["openhands_state_dir"], "/var/lib/docker/openhands")
        self.assertEqual(defaults["openhands_conversation_memory_limit"], "4g")
        self.assertEqual(defaults["openhands_conversation_cpus"], "2.0")
        self.assertEqual(defaults["openhands_conversation_pids_limit"], 512)

    def test_tasks_only_create_the_user_and_state_directory(self):
        tasks = _load(ROLE / "tasks" / "main.yml")
        modules = [
            key for task in tasks for key in task if key.startswith("ansible.builtin.")
        ]
        self.assertEqual(
            sorted(set(modules)),
            ["ansible.builtin.file", "ansible.builtin.group", "ansible.builtin.user"],
        )

        user = _task(tasks, "Create the OpenHands system user")["ansible.builtin.user"]
        self.assertEqual(user["groups"], "docker")
        self.assertTrue(user["append"])
        self.assertEqual(user["home"], "{{ openhands_state_dir }}")
        self.assertIs(user["create_home"], False)

        state_dir = _task(tasks, "Create the OpenHands state directory")["ansible.builtin.file"]
        self.assertEqual(state_dir["mode"], "0750")
        self.assertEqual(
            (state_dir["owner"], state_dir["group"]),
            ("{{ openhands_user }}", "{{ openhands_user }}"),
        )

    def test_role_never_references_bao_facts(self):
        role_files = sorted(ROLE.rglob("*.yml")) + [GROUP_VARS]
        self.assertGreaterEqual(len(role_files), 4)
        for path in role_files:
            self.assertNotIn(
                "bao_",
                path.read_text(encoding="utf-8"),
                f"{path.relative_to(ROOT)} must not read bao_* secret facts",
            )


if __name__ == "__main__":
    unittest.main()
