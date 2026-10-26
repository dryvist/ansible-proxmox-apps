"""Homebox API-key publication matches the Nautobot feed contract."""

from pathlib import Path
import re
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
DEFAULTS = yaml.safe_load(
    (REPO / "roles/homebox/defaults/main.yml").read_text(encoding="utf-8")
)
VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/homebox_group.yml").read_text(encoding="utf-8")
)
ROLE_TASKS = yaml.safe_load(
    (REPO / "roles/homebox/tasks/main.yml").read_text(encoding="utf-8")
)
API_KEY_TASKS = yaml.safe_load(
    (REPO / "roles/homebox/tasks/api_key.yml").read_text(encoding="utf-8")
)
SECRET_WORDS = re.compile(r"password|token")


def is_assert(task):
    return "ansible.builtin.assert" in task


class HomeboxAPIKeyContract(unittest.TestCase):
    def test_openbao_path_and_field_match_the_feed_target(self):
        target = next(
            target for target in VARS["homebox_feed_targets"] if target["name"] == "main"
        )
        self.assertEqual(
            DEFAULTS["homebox_api_key_openbao_path"],
            target["api_key_secret"]["path"],
        )
        self.assertEqual(
            DEFAULTS["homebox_api_key_openbao_field"],
            target["api_key_secret"]["field"],
        )

    def test_publish_flag_is_off_by_default_and_on_for_homebox(self):
        self.assertIs(DEFAULTS["homebox_api_key_publish_openbao"], False)
        self.assertIs(VARS["homebox_api_key_publish_openbao"], True)

    def test_secret_handling_tasks_suppress_logs(self):
        # Asserts only test presence and must stay visible, because no_log
        # would hide their fail_msg. Every other task that names a token or a
        # password needs no_log.
        checked = []
        for task in API_KEY_TASKS:
            name = task["name"]
            with self.subTest(task=name):
                if is_assert(task):
                    self.assertIsNot(task.get("no_log"), True)
                    continue
                if SECRET_WORDS.search(yaml.safe_dump(task).lower()):
                    checked.append(name)
                    self.assertIs(task.get("no_log"), True)
        # Non-vacuous: the login, list, OpenBao read, mint and publish tasks
        # all name a token or password, so at least these must be checked.
        self.assertGreaterEqual(len(checked), 5)

    def test_main_includes_api_key_tasks_behind_publish_flag_and_check_mode(self):
        includes = [
            task
            for task in ROLE_TASKS
            if isinstance(task.get("ansible.builtin.include_tasks"), dict)
            and task["ansible.builtin.include_tasks"].get("file") == "api_key.yml"
        ]
        self.assertEqual(len(includes), 1)
        include = includes[0]
        self.assertEqual(
            include["ansible.builtin.include_tasks"]["apply"]["tags"], ["homebox"]
        )
        self.assertIn("homebox", include.get("tags", []))
        self.assertEqual(
            include.get("when"),
            ["homebox_api_key_publish_openbao | bool", "not ansible_check_mode"],
        )


if __name__ == "__main__":
    unittest.main()
