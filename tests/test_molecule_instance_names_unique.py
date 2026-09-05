"""Instance names must carry the per-job suffix, or concurrent runs collide.

Every scenario names its platforms statically, and the Docker daemon a run
talks to is not necessarily its own. Two runs of one scenario against the same
daemon therefore address the same containers: the second run's create adopts
the first run's instances, and either run's destroy removes them out from under
the other. Appending ``${CI_INSTANCE_SUFFIX}`` scopes every name to the job
that created it; the variable is unset outside CI, where Molecule interpolates
it to nothing and a local run keeps the bare name.

An inventory key that names an instance is the same name and must carry the
same suffix, or the host_vars it holds attach to nothing.
"""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SUFFIX = "${CI_INSTANCE_SUFFIX}"
WORKFLOW = ROOT / ".github" / "workflows" / "_molecule.yml"


def _scenarios():
    return sorted(ROOT.glob("molecule/*/molecule.yml"))


class MoleculeInstanceNamesAreUniquePerJob(unittest.TestCase):
    def test_every_platform_name_carries_the_suffix(self):
        scenarios = _scenarios()
        self.assertTrue(scenarios, "no molecule scenario was found")
        for path in scenarios:
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            platforms = config.get("platforms") or []
            self.assertTrue(platforms, f"{path} declares no platforms")
            for platform in platforms:
                with self.subTest(scenario=path.parent.name, platform=platform["name"]):
                    self.assertTrue(
                        platform["name"].endswith(SUFFIX),
                        f"platform name {platform['name']!r} is shared across jobs",
                    )

    def test_inventory_keys_match_the_declared_instances(self):
        for path in _scenarios():
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            inventory = (config.get("provisioner") or {}).get("inventory") or {}
            names = {p["name"] for p in config.get("platforms") or []}
            for key in inventory.get("host_vars") or {}:
                with self.subTest(scenario=path.parent.name, host=key):
                    # A host_vars key either names a container, and must then
                    # match a platform exactly, or is an inventory-only fixture,
                    # which still carries the suffix so the two never converge.
                    self.assertTrue(
                        key in names or key.endswith(SUFFIX),
                        f"host_vars key {key!r} does not name a per-job instance",
                    )

    def test_ci_sets_the_suffix(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        env = next(
            step["env"]
            for step in workflow["jobs"]["test"]["steps"]
            if "molecule test" in step.get("run", "")
        )
        self.assertIn("CI_INSTANCE_SUFFIX", env)
        self.assertNotEqual(env["CI_INSTANCE_SUFFIX"].strip(), "")


if __name__ == "__main__":
    unittest.main()
