"""Keep Technitium version updates separate from Renovate's shared group."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RenovateTechnitiumIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))

    def test_minor_and_patch_updates_use_a_dedicated_enabled_rule(self):
        self.assertIn("github>JacobPEvans/.github", self.config["extends"])
        rules = [
            rule
            for rule in self.config["packageRules"]
            if rule.get("matchDatasources") == ["docker"]
            and rule.get("matchDepNames") == ["technitium/dns-server"]
        ]
        self.assertEqual(len(rules), 2)

        major = next(rule for rule in rules if rule.get("matchUpdateTypes") == ["major"])
        minor_patch = next(
            rule for rule in rules if rule.get("matchUpdateTypes") == ["minor", "patch"]
        )
        self.assertIs(major["enabled"], False)
        self.assertEqual(minor_patch["groupName"], "technitium")
        self.assertIs(minor_patch["automerge"], False)
        self.assertIs(minor_patch["enabled"], True)
        self.assertIs(self.config["packageRules"][-1], minor_patch)
        self.assertNotIn("matchPackageNames", minor_patch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
