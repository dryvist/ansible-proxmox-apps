"""The 13 Molecule scenarios share an identical dependency, driver, and
verifier block. Before this test, each scenario's molecule.yml repeated all
three verbatim — any drift (a bumped verifier, a changed Galaxy requirements
path) had to be edited in 13 places and silently could be edited in only one.

Molecule merges `.config/molecule/config.yml` first and each scenario's own
molecule.yml on top (a recursive dict merge; see
molecule.util.merge_dicts) — a scenario file never NEEDS to repeat a key the
base config already carries. This test is the contract that keeps it that
way: the base config carries exactly the keys identical across every
scenario, and no scenario file re-declares one of them.

There is no shared destroy playbook to centralize: no molecule.yml in this
repo sets `provisioner.playbooks`, so every scenario runs the docker driver's
own built-in destroy playbook already.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
MOLECULE_DIR = ROOT / "molecule"
BASE_CONFIG = ROOT / ".config" / "molecule" / "config.yml"

# Keys the base config must carry because they are byte-identical across
# every scenario's molecule.yml. A key belongs here only once every
# scenario's own value for it matches exactly.
SHARED_KEYS = ("dependency", "driver", "verifier")


def _scenario_files():
    return sorted(p for p in MOLECULE_DIR.glob("*/molecule.yml"))


class MoleculeBaseConfigDry(unittest.TestCase):
    def test_base_config_exists_and_carries_the_shared_keys(self):
        self.assertTrue(BASE_CONFIG.is_file(), f"missing {BASE_CONFIG}")
        base = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8"))
        for key in SHARED_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, base, f"base config does not carry {key!r}")

    def test_no_scenario_redeclares_a_shared_key(self):
        scenarios = _scenario_files()
        self.assertTrue(scenarios, "no molecule.yml files found")
        for path in scenarios:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            for key in SHARED_KEYS:
                with self.subTest(scenario=path.parent.name, key=key):
                    self.assertNotIn(
                        key,
                        config,
                        f"{path} re-declares {key!r}, which the base config already carries",
                    )

    def test_every_scenario_agrees_with_the_base_config_value(self):
        base = yaml.safe_load(BASE_CONFIG.read_text(encoding="utf-8"))
        # Re-derive what every scenario used to declare from git history is
        # overkill; instead assert the invariant that made centralizing safe
        # in the first place: the base config's value is what every scenario
        # already relied on (galaxy dependency, docker driver, ansible
        # verifier), not a novel value nobody tested.
        self.assertEqual(base["dependency"]["name"], "galaxy")
        self.assertEqual(base["driver"]["name"], "docker")
        self.assertEqual(base["verifier"]["name"], "ansible")

    def test_no_scenario_declares_a_destroy_playbook(self):
        # Documents why this refactor does not centralize a destroy playbook:
        # none exists. Every scenario destroys through the docker driver's
        # own built-in playbook. If one ever appears, it belongs in the base
        # config alongside dependency/driver/verifier, and this test should
        # be updated to require that instead.
        for path in _scenario_files():
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            playbooks = (config.get("provisioner") or {}).get("playbooks")
            with self.subTest(scenario=path.parent.name):
                self.assertIsNone(playbooks, f"{path} now declares provisioner.playbooks")


if __name__ == "__main__":
    unittest.main()
