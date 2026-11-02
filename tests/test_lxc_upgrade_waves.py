# Copyright (c) 2026 JacobPEvans
# GNU General Public License v3.0+ (see LICENSE or https://www.gnu.org/licenses/gpl-3.0.txt)
"""The upgrade_wave_<n> group each LXC container gets from the inventory loader.

Each case renders the real expression in inventory/load_tofu/lxc_groups.yml
with Ansible's Templar, the engine the loader uses.
"""

import bisect
import unittest
from collections import Counter
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template


ROOT = Path(__file__).resolve().parents[1]
EXPRESSION = yaml.safe_load(
    (ROOT / "inventory/load_tofu/lxc_groups.yml").read_text(encoding="utf-8")
)["add_lxc_hosts_groups"]
WAVE_SIZE = 12
WAVE_PREFIX = "upgrade_wave_"
# Sixty names, not zero-padded, so the sorted order differs from the
# insertion order. "Zeta" is capitalised: a case-sensitive sort puts it first.
KEYS = [f"{prefix}-{n}" for prefix in ("svc", "app", "dns", "mail", "Zeta") for n in range(1, 13)]


def _groups(key, containers, with_inventory=True):
    templar = Templar(loader=DataLoader())
    variables = {"item": {"key": key, "value": containers[key]}}
    if with_inventory:
        variables["tofu_data"] = {"containers": containers}
    templar.available_variables = variables
    return templar.template(trust_as_template(EXPRESSION))


def _waves(containers):
    """Map each container key to the upgrade_wave_* groups the loader gives it."""
    return {
        key: [group for group in _groups(key, containers) if group.startswith(WAVE_PREFIX)]
        for key in containers
    }


class UpgradeWaves(unittest.TestCase):
    def setUp(self):
        self.containers = {key: {"tags": []} for key in KEYS}
        self.waves = _waves(self.containers)

    def test_each_container_gets_exactly_one_wave(self):
        for key in KEYS:
            with self.subTest(key=key):
                self.assertEqual(len(self.waves[key]), 1)

    def test_wave_is_the_sorted_position_floor_divided_by_wave_size(self):
        for position, key in enumerate(sorted(KEYS)):
            with self.subTest(key=key):
                self.assertEqual(self.waves[key], [f"{WAVE_PREFIX}{position // WAVE_SIZE}"])

    def test_no_wave_exceeds_wave_size_and_numbers_start_at_zero(self):
        members = Counter(group for groups in self.waves.values() for group in groups)
        self.assertLessEqual(max(members.values()), WAVE_SIZE)
        numbers = sorted(int(group[len(WAVE_PREFIX):]) for group in members)
        self.assertEqual(numbers, list(range(len(numbers))))

    def test_waves_zero_to_three_and_the_rest_cover_every_key_once(self):
        first_four = {f"{WAVE_PREFIX}{n}" for n in range(4)}
        in_first_four = [key for key in KEYS if first_four & set(self.waves[key])]
        rest = [key for key in KEYS if not first_four & set(self.waves[key])]
        self.assertEqual(len(rest), len(KEYS) - 4 * WAVE_SIZE)
        covered = Counter(in_first_four + rest)
        self.assertEqual(set(covered), set(KEYS))
        self.assertEqual(set(covered.values()), {1})

    def test_adding_a_container_moves_only_keys_at_or_after_its_position(self):
        new_key = "app-13"
        after = _waves({**self.containers, new_key: {"tags": []}})
        ordered = sorted(KEYS)
        position = bisect.bisect_left(ordered, new_key)
        moved = [key for key in KEYS if after[key] != self.waves[key]]
        self.assertTrue(moved)
        for key in moved:
            with self.subTest(key=key):
                self.assertGreaterEqual(ordered.index(key), position)
        self.assertEqual(after[new_key], [f"{WAVE_PREFIX}{position // WAVE_SIZE}"])

    def test_without_inventory_context_no_wave_group_is_added(self):
        groups = _groups(KEYS[0], self.containers, with_inventory=False)
        self.assertEqual([group for group in groups if group.startswith(WAVE_PREFIX)], [])


if __name__ == "__main__":
    unittest.main()
