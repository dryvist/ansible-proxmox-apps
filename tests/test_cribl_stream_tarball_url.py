#!/usr/bin/env python3
"""Cribl release and build identity comes from the homelab-contracts catalog."""

import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALL_VARS = ROOT / "inventory" / "group_vars" / "all.yml"
CRIBL_EDGE_VARS = ROOT / "inventory" / "group_vars" / "cribl_edge.yml"
CRIBL_STREAM_VARS = ROOT / "inventory" / "group_vars" / "cribl_stream_group.yml"
CRIBL_STREAM_DEFAULTS = ROOT / "roles" / "cribl_stream" / "defaults" / "main" / "00-install.yml"
CRIBL_DOCKER_STACK_DEFAULTS = ROOT / "roles" / "cribl_docker_stack" / "defaults" / "main.yml"
OBJECT_STORAGE_DEFAULTS = ROOT / "roles" / "object_storage" / "defaults" / "main" / "00-core.yml"
RENOVATE_JSON = ROOT / "renovate.json"

# A literal version, build hash, or sha256 digest assigned to a variable
# (not appearing only in a comment or documentation string). Matches
# `key: "4.20.0"`, `key: "cee79842"`, or a 64-hex digest on a non-comment
# line.
_LITERAL_VERSION_HASH_RE = re.compile(
    r'^\s*[A-Za-z0-9_]+:\s*"(?:\d+\.\d+\.\d+|[0-9a-f]{8}|[0-9a-f]{64})"\s*$'
)


def _non_comment_lines(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("#"):
            yield line


class CriblNoLiteralVersionOrHash(unittest.TestCase):
    def test_no_literal_version_hash_or_sha_under_cribl_stream_or_docker_stack(self):
        for role_dir in ("cribl_stream", "cribl_docker_stack"):
            for path in sorted((ROOT / "roles" / role_dir).rglob("*.yml")):
                for line in _non_comment_lines(path):
                    self.assertNotRegex(
                        line,
                        _LITERAL_VERSION_HASH_RE,
                        f"{path.relative_to(ROOT)} hardcodes a version/hash/sha256 "
                        f"literal ({line.strip()!r}) -- read cribl_version instead "
                        "of declaring a role-local pin.",
                    )


class CriblConsumersReadTheSharedCatalog(unittest.TestCase):
    def test_catalog_path_uses_the_installed_homelab_contracts_collection(self):
        variables = yaml.safe_load(ALL_VARS.read_text(encoding="utf-8"))
        self.assertIn("ansible.builtin.first_found", variables["cribl_catalog_path"])
        self.assertIn("COLLECTIONS_PATHS", variables["cribl_catalog_path"])
        self.assertIn("cribl.json", variables["cribl_catalog_path"])
        self.assertIn("ansible.builtin.file", variables["cribl_catalog"])
        self.assertIn("from_json", variables["cribl_catalog"])
        self.assertEqual(variables["cribl_version"], "{{ cribl_catalog.version }}")
        self.assertIn("cribl_version.split('-')[0]", variables["cribl_docker_tag"])

    def test_cribl_stream_uses_full_build_id_in_its_url(self):
        defaults = yaml.safe_load(CRIBL_STREAM_DEFAULTS.read_text(encoding="utf-8"))
        self.assertIn("cribl_version", defaults["cribl_stream_version"])
        url = defaults["cribl_stream_tarball_url"]
        self.assertIn("cribl_stream_version.split('-')[0]", url)
        self.assertIn("cribl_stream_version", url)
        self.assertNotIn("latest", url)

    def test_cribl_edge_mirror_key_uses_catalog_version(self):
        variables = yaml.safe_load(CRIBL_EDGE_VARS.read_text(encoding="utf-8"))
        self.assertIn("cribl_version", variables["cribl_edge_tarball_url"])

    def test_docker_tag_derives_from_the_catalog_version(self):
        variables = yaml.safe_load(ALL_VARS.read_text(encoding="utf-8"))
        defaults = yaml.safe_load(CRIBL_DOCKER_STACK_DEFAULTS.read_text(encoding="utf-8"))
        self.assertIn("cribl_version.split('-')[0]", variables["cribl_docker_tag"])
        self.assertIn("cribl_docker_tag", defaults["cribl_docker_stack_image"])

    def test_object_storage_mirror_uses_the_fixed_catalog_url_and_sidecar(self):
        defaults = yaml.safe_load(OBJECT_STORAGE_DEFAULTS.read_text(encoding="utf-8"))
        mirrors = defaults.get("object_storage_infra_mirrors") or []
        cribl_entries = [entry for entry in mirrors if entry.get("name") == "cribl"]
        self.assertTrue(cribl_entries, "No 'cribl' entry in object_storage_infra_mirrors")
        entry = cribl_entries[0]
        self.assertIn("cribl_version", entry["key"])
        self.assertIn("cribl_version.split('-')[0]", entry["url"])
        self.assertIn("cribl_version", entry["url"])
        self.assertEqual(entry["sidecar"], "sha256")
        self.assertNotIn("pointer_url", entry)

    def test_pack_sets_are_not_duplicated_in_group_vars(self):
        edge = yaml.safe_load(CRIBL_EDGE_VARS.read_text(encoding="utf-8"))
        stream = yaml.safe_load(CRIBL_STREAM_VARS.read_text(encoding="utf-8"))
        self.assertNotIn("cribl_packs_for_edge", edge)
        self.assertNotIn("cribl_packs_for_stream", stream)


class CriblVersionIsNotDuplicatedInRenovate(unittest.TestCase):
    def test_renovate_has_no_separate_cribl_version_manager(self):
        renovate_config = json.loads(RENOVATE_JSON.read_text(encoding="utf-8"))
        managers = renovate_config.get("customManagers", [])
        self.assertFalse(
            any(manager.get("depNameTemplate") == "cribl/cribl" for manager in managers)
        )
        self.assertFalse(
            any("cribl_version" in json.dumps(manager) for manager in managers)
        )


if __name__ == "__main__":
    unittest.main()
