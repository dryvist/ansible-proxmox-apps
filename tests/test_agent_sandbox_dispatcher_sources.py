"""The dispatcher wrapper sources every pinned helper, in the upstream build order."""

from pathlib import Path
import unittest

import yaml

ROLE = Path(__file__).resolve().parents[1] / "roles" / "agent_sandbox"


class DispatcherSources(unittest.TestCase):
    def test_wrapper_sources_are_pinned_and_ordered(self):
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
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


if __name__ == "__main__":
    unittest.main()
