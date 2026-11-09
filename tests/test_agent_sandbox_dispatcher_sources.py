"""The dispatcher wrapper sources every pinned helper, in the upstream build order."""

from pathlib import Path
import re
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.role import Role

ROLE = Path(__file__).resolve().parents[1] / "roles" / "agent_sandbox"


class DispatcherSources(unittest.TestCase):
    def test_ansible_loads_both_default_sections(self):
        role = Role()
        role._role_path = str(ROLE)
        role._loader = DataLoader()
        defaults = role._load_role_yaml("defaults", allow_dir=True)

        self.assertIs(defaults["agent_sandbox_job_github_write"], False)
        self.assertIs(defaults["agent_sandbox_ci_resolver_enabled"], False)
        self.assertEqual(
            defaults["agent_sandbox_ci_resolver_source_commit"],
            "{{ agent_sandbox_dispatch_source_commit }}",
        )

    def test_wrapper_sources_are_pinned_and_ordered(self):
        defaults = yaml.safe_load((ROLE / "defaults" / "main" / "00-runtime.yml").read_text())
        pinned = [item["name"] for item in defaults["agent_sandbox_dispatch_sources"]]
        tasks = yaml.safe_load(
            (ROLE / "tasks" / "main" / "dispatcher_install.yml").read_text()
        )
        wrapper = next(
            task for task in tasks
            if task.get("name") == "Install the dispatcher and its SSH entry point"
        )
        sourced = [name for item in wrapper["loop"] for name in item["sources"]]

        self.assertEqual(sorted(sourced), sorted(pinned))
        # nix/agent-dispatch.nix concatenates the result helper before the dispatcher.
        self.assertEqual(
            wrapper["loop"][0]["sources"], ["agent-dispatch-result.sh", "agent-dispatch.sh"]
        )
        self.assertIn("{% for source in item.sources %}", wrapper["ansible.builtin.copy"]["content"])

    def test_release_pins_agree(self):
        defaults = yaml.safe_load((ROLE / "defaults" / "main" / "00-runtime.yml").read_text())
        commit = defaults["agent_sandbox_dispatch_source_commit"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        # The staged dispatch helpers and the ci-resolver stage derive from the
        # one source commit.
        self.assertEqual(
            defaults["agent_sandbox_dispatch_stage_prefix"],
            "/tmp/agent-sandbox-{{ agent_sandbox_dispatch_source_commit[:8] }}-",
        )
        ci_resolver = yaml.safe_load((ROLE / "defaults" / "main" / "10-ci-resolver.yml").read_text())
        self.assertEqual(
            ci_resolver["agent_sandbox_ci_resolver_source_commit"],
            "{{ agent_sandbox_dispatch_source_commit }}",
        )
        # The dispatcher shares the single literal Web image pin, and the
        # template_render verification asserts the same digest.
        self.assertEqual(
            defaults["agent_sandbox_dispatch_image"], "{{ agent_sandbox_zcode_web_image }}"
        )
        digest = re.search(r"[0-9a-f]{64}", defaults["agent_sandbox_zcode_web_image"]).group()
        verify = (ROLE.parents[1] / "tests" / "template_render" / "verify" / "agent_sandbox.yml").read_text()
        self.assertIn(digest, verify)


if __name__ == "__main__":
    unittest.main()
