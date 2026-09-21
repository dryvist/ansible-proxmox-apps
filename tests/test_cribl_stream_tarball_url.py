#!/usr/bin/env python3
"""Cribl version/hash/checksum must never be hardcoded anywhere in the repo.

One org-wide pin, inventory/group_vars/all.yml `cribl_version`, is the only
literal Cribl version in this repository (Renovate-managed). Every consumer
-- roles/cribl_stream/defaults/main/00-install.yml (`cribl_stream_version`),
inventory/group_vars/cribl_edge.yml (the mirror tarball key), and
roles/cribl_docker_stack/defaults/main.yml (the image tag) -- reads it rather
than declaring its own pin, so a version bump is one edit instead of three
that can silently drift out of step (exactly how the pre-split
cribl_stream_build_hash/cribl_stream_tarball_sha256 pair could drift from
cribl_stream_version if only one was bumped).

No build hash or sha256 digest is committed anywhere either: Cribl's CDN
filenames carry a per-build hash that isn't derivable from the version
string, so it is resolved at run time (roles/cribl_stream/tasks/
mirror_seed.yml, from the CDN's own `dl/latest-x64` pointer) rather than
pinned as a default that would go stale the moment the CDN rotates a build
without a version bump.
"""

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALL_VARS = ROOT / "inventory" / "group_vars" / "all.yml"
CRIBL_EDGE_VARS = ROOT / "inventory" / "group_vars" / "cribl_edge.yml"
CRIBL_STREAM_DEFAULTS = ROOT / "roles" / "cribl_stream" / "defaults" / "main" / "00-install.yml"
CRIBL_DOCKER_STACK_DEFAULTS = ROOT / "roles" / "cribl_docker_stack" / "defaults" / "main.yml"
RENOVATE_JSON = ROOT / "renovate.json"

# A literal version, build hash, or sha256 digest assigned to a variable
# (not appearing only in a comment or documentation string). Matches
# `key: "4.20.0"`, `key: "cee79842"`, `key: "8602d5...f9"` -- any quoted
# token that looks like a bare semver, an 8-hex-char build hash, or a
# 64-hex-char digest, sitting on a non-comment line.
_LITERAL_VERSION_HASH_RE = re.compile(
    r'^\s*[A-Za-z0-9_]+:\s*"(?:\d+\.\d+\.\d+|[0-9a-f]{8}|[0-9a-f]{64})"\s*$'
)


def _non_comment_lines(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("#"):
            continue
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


class CriblConsumersReadTheSharedVersion(unittest.TestCase):
    def _assert_references_cribl_version(self, path: Path, var_name: str):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIn(var_name, data, f"{var_name} not declared in {path}")
        value = str(data[var_name])
        self.assertIn(
            "cribl_version",
            value,
            f"{path.relative_to(ROOT)}'s {var_name} ({value!r}) does not "
            "reference the shared cribl_version -- it can drift from the "
            "single org-wide pin.",
        )

    def test_cribl_stream_defaults_read_cribl_version(self):
        self._assert_references_cribl_version(CRIBL_STREAM_DEFAULTS, "cribl_stream_version")

    def test_cribl_edge_tarball_url_reads_cribl_version(self):
        self._assert_references_cribl_version(CRIBL_EDGE_VARS, "cribl_edge_tarball_url")

    def test_cribl_docker_stack_image_reads_cribl_version(self):
        self._assert_references_cribl_version(CRIBL_DOCKER_STACK_DEFAULTS, "cribl_docker_stack_image")


class CriblVersionIsRenovateManaged(unittest.TestCase):
    def test_renovate_custom_manager_matches_the_all_yml_pin(self):
        renovate_config = yaml.safe_load(RENOVATE_JSON.read_text(encoding="utf-8"))
        managers = [
            m
            for m in renovate_config.get("customManagers", [])
            if m.get("depNameTemplate") == "cribl/cribl"
        ]
        self.assertTrue(
            managers,
            "renovate.json has no customManager tracking cribl/cribl -- "
            "cribl_version would never be flagged for a bump.",
        )
        manager = managers[0]
        all_yml_text = ALL_VARS.read_text(encoding="utf-8")
        # Renovate's regex manager uses named groups as `(?<name>...)`
        # (.NET/JS style); Python's re module requires `(?P<name>...)`.
        matched = any(
            re.search(pattern.replace("(?<", "(?P<"), all_yml_text)
            for pattern in manager["matchStrings"]
        )
        self.assertTrue(
            matched,
            f"None of the cribl/cribl customManager's matchStrings "
            f"{manager['matchStrings']!r} match the actual cribl_version "
            f"line in {ALL_VARS.relative_to(ROOT)} -- Renovate would silently "
            "stop tracking the pin.",
        )
        self.assertEqual(manager.get("datasourceTemplate"), "docker")


if __name__ == "__main__":
    unittest.main()
