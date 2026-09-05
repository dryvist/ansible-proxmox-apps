"""A scenario that starts a Docker daemon inside its instance needs a volume.

The instance is itself a container, so its root filesystem is an overlay. An
inner daemon left on that root unpacks image layers into it, and the kernel
does not accept an overlay as the upper layer of another overlay: a layer
carrying a whiteout entry fails on the mknod that records it. Layers without
one extract normally, so the failure reads as a bad image rather than a bad
scenario, and it only appears once someone deploys an image built with a
delete in a later layer.

Which scenarios nest is derived, not listed: the CI scenario selector already
closes each scenario over the roles it reaches, meta dependencies included, so
a scenario nests exactly when that closure contains docker_engine.
"""

import importlib.util
from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / ".github" / "scripts" / "select-molecule-scenarios.py"
# Where an inner daemon keeps image and container layers. Which one is in use
# depends on the image store it selected, so both are covered.
LAYER_ROOTS = ("/var/lib/docker", "/var/lib/containerd")


def _load_selector():
    spec = importlib.util.spec_from_file_location("scenario_selector", SELECTOR)
    if spec is None or spec.loader is None:
        raise ImportError(f"no loader for {SELECTOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nesting_scenarios():
    selector = _load_selector()
    known = selector.roles_on_disk()
    return sorted(
        scenario
        for scenario, roles in selector.scenario_roles(known).items()
        if "docker_engine" in roles
    )


class MoleculeInnerDockerVolumes(unittest.TestCase):
    def test_nesting_scenarios_give_the_inner_daemon_a_volume(self):
        scenarios = _nesting_scenarios()
        self.assertTrue(scenarios, "no scenario was found to run an inner daemon")
        for scenario in scenarios:
            config = yaml.safe_load(
                (ROOT / "molecule" / scenario / "molecule.yml").read_text(encoding="utf-8")
            )
            for platform in config["platforms"]:
                with self.subTest(scenario=scenario, platform=platform["name"]):
                    volumes = platform.get("volumes", [])
                    for root in LAYER_ROOTS:
                        self.assertIn(
                            root,
                            volumes,
                            f"{root} is left on the instance's own overlay rootfs",
                        )


if __name__ == "__main__":
    unittest.main()
