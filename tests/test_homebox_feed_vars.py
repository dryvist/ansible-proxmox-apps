"""The Nautobot -> Homebox feed defaults to a render-only run and declares valid scope."""

from pathlib import Path
import re
import unittest

import yaml

REPO = Path(__file__).resolve().parents[1]
VARS = yaml.safe_load(
    (REPO / "inventory/group_vars/homebox_group.yml").read_text(encoding="utf-8")
)
SECRET_PATH = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+/(ro|rw|admin)$")


class HomeboxFeedVars(unittest.TestCase):
    def test_apply_is_off_by_default(self):
        self.assertIs(VARS["homebox_feed_apply"], False)

    def test_every_target_reads_a_grammar_conformant_secret_under_the_ingress_domain(self):
        self.assertTrue(VARS["homebox_feed_targets"])
        for target in VARS["homebox_feed_targets"]:
            with self.subTest(target=target["name"]):
                self.assertRegex(target["api_key_secret"]["path"], SECRET_PATH)
                self.assertRegex(target["api_key_secret"]["field"], r"^[A-Z][A-Z0-9_]*$")
                self.assertTrue(target["url"].startswith("https://homebox.{{ ingress_domain }}"))

    def test_exclude_patterns_compile_and_never_skip_a_force_included_prefix(self):
        prefixes = VARS["homebox_feed_always_include_asset_tag_prefixes"]
        for pattern in VARS["homebox_feed_exclude_asset_tag_patterns"]:
            compiled = re.compile(pattern)
            for prefix in prefixes:
                with self.subTest(pattern=pattern, prefix=prefix):
                    self.assertIsNone(compiled.search(prefix + "-X"))

    def test_price_floor_is_five_dollars(self):
        self.assertEqual(VARS["homebox_feed_min_price_cents"], 500)


if __name__ == "__main__":
    unittest.main()
