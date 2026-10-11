"""Tasks the agent_sandbox role delegates to the controller must not inherit host privilege escalation."""

from pathlib import Path
import unittest

import yaml

ROLE_TASKS = Path(__file__).resolve().parents[1] / "roles" / "agent_sandbox" / "tasks"
NESTED = ("block", "rescue", "always")


def walk(tasks):
    for task in tasks or []:
        yield task
        for key in NESTED:
            yield from walk(task.get(key))


def delegated_to_controller():
    for path in sorted(ROLE_TASKS.rglob("*.yml")):
        for task in walk(yaml.safe_load(path.read_text(encoding="utf-8"))):
            if task.get("delegate_to") == "localhost":
                yield f"{path.relative_to(ROLE_TASKS)}: {task['name']}", task


class ControllerTasks(unittest.TestCase):
    def test_every_controller_task_overrides_the_become_variable(self):
        tasks = list(delegated_to_controller())
        self.assertGreaterEqual(len(tasks), 6)
        missing = [
            label
            for label, task in tasks
            if task.get("vars", {}).get("ansible_become") is not False
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
