"""Every converge-domain AppRole on the rotated-domain TTL is in the scheduled rotation set."""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = ROOT / "roles" / "openbao" / "defaults" / "main"
ROTATED_TTL_REF = "{{ openbao_rotated_domain_secret_id_ttl }}"
VAR_REF = re.compile(r"\{\{\s*(\w+)\s*\}\}")
NAME_VAR = re.compile(r"\b(openbao_\w+_approle_names?)\b")


def _defaults() -> dict:
    merged: dict = {}
    for path in sorted(DEFAULTS.glob("*.yml")):
        merged.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return merged


def _resolve(defaults: dict, value):
    if isinstance(value, list):
        return [name for item in value for name in _resolve(defaults, item)]
    match = VAR_REF.fullmatch(str(value).strip())
    if match:
        return _resolve(defaults, defaults[match.group(1)])
    return [str(value)]


def rotation_set(defaults: dict, expression: str) -> set:
    names: set = set()
    for var in NAME_VAR.findall(expression):
        names.update(_resolve(defaults, defaults[var]))
    return names


def missing_from_rotation(defaults: dict, expression: str) -> set:
    rotated_ttl = {
        name
        for name, ttl in defaults["openbao_approle_secret_id_ttl_overrides"].items()
        if ttl == ROTATED_TTL_REF
    }
    # Outside the domain set by design: the rotator rotates itself last, and
    # the private Hermes agent stays out of scheduled rotation (its own
    # verify file asserts that).
    for exempt in (
        "openbao_approle_secret_id_rotate_scheduled_approle_name",
        "openbao_hermes_private_agent_approle_name",
    ):
        rotated_ttl -= set(_resolve(defaults, defaults[exempt]))
    return rotated_ttl - rotation_set(defaults, expression)


class DomainRotationCatalogContract(unittest.TestCase):
    def setUp(self):
        self.defaults = _defaults()
        self.expression = self.defaults["openbao_secrets_domain_approle_names"]

    def test_every_rotated_ttl_domain_is_in_the_rotation_set(self):
        self.assertEqual(missing_from_rotation(self.defaults, self.expression), set())

    def test_ai_donna_rotates_on_the_domain_margin(self):
        name = self.defaults["openbao_ai_donna_approle_name"]
        self.assertIn(name, rotation_set(self.defaults, self.expression))
        self.assertEqual(
            self.defaults["openbao_approle_secret_id_ttl_overrides"][name], ROTATED_TTL_REF
        )

    def test_ai_donna_pair_lands_under_its_converge_domain_prefix(self):
        name = self.defaults["openbao_ai_donna_approle_name"]
        prefix = self.defaults["openbao_approle_env_prefix_overrides"][name]
        self.assertNotEqual(prefix, name)
        self.assertTrue(name.endswith(prefix))

    def test_a_domain_dropped_from_the_rotation_set_fails(self):
        dropped = self.expression.replace("openbao_ai_donna_approle_name", "")
        self.assertIn(
            self.defaults["openbao_ai_donna_approle_name"],
            missing_from_rotation(self.defaults, dropped),
        )


if __name__ == "__main__":
    unittest.main()
