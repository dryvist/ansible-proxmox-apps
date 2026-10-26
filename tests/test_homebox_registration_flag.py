"""Homebox sign-ups follow the first-account flag in the inventory.

The flag is true once the first account exists, which closes registration. A
fresh instance sets it to false to open registration for that first account.
"""

from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

REPO = Path(__file__).resolve().parents[1]
VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/homebox_group.yml").read_text(encoding="utf-8")
)
ENV = Environment(undefined=StrictUndefined)
ENV.filters["bool"] = lambda value: str(value).strip().lower() in ("true", "yes", "1")


def allow_registration(first_account_created):
    template = ENV.from_string(VARS["homebox_options_allow_registration"])
    return template.render(homebox_first_account_created=first_account_created).strip()


class HomeboxRegistrationFlag(unittest.TestCase):
    def test_the_live_instance_has_its_first_account(self):
        self.assertIs(VARS["homebox_first_account_created"], True)

    def test_registration_is_closed_once_the_first_account_exists(self):
        self.assertEqual(allow_registration(True), "False")

    def test_registration_is_open_while_the_first_account_is_missing(self):
        self.assertEqual(allow_registration(False), "True")


if __name__ == "__main__":
    unittest.main()
