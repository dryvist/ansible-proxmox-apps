#!/usr/bin/env python3
"""Cribl Stream's tarball URL must always carry the build hash Cribl requires.

Cribl's real download filenames are cribl-{version}-{hash}-linux-x64.tgz; a
bare cribl-{version}-linux-x64.tgz 404s. Both the CDN default template
(roles/cribl_stream/defaults/main/00-install.yml) and the object-storage
mirror override
(inventory/group_vars/cribl_stream_group.yml) build this filename from
separate `cribl_stream_version`/`cribl_stream_build_hash` variables, so a
version bump that only updates one of the two silently breaks downloads on
whichever host resolves the other. This test renders both templates and
checks the hash actually appears in the produced filename, not just that the
template renders without error.

Also asserts cribl_stream_tarball_sha256 looks like a real sha256 (64 hex
chars) -- get_url's checksum param fails open into "always redownload" on a
malformed value rather than failing the converge, so a typo here would not
otherwise be caught.
"""

import re
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = ROOT / "roles" / "cribl_stream" / "defaults" / "main" / "00-install.yml"
GROUP_VARS = ROOT / "inventory" / "group_vars" / "cribl_stream_group.yml"

TEST_VERSION = "4.20.0"
TEST_HASH = "cee79842"


def _load_var(path: Path, name: str) -> str:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert name in data, f"{name} not declared in {path}"
    return data[name]


class CriblStreamTarballUrl(unittest.TestCase):
    def setUp(self):
        self.env = Environment()
        self.context = {
            "cribl_stream_version": TEST_VERSION,
            "cribl_stream_build_hash": TEST_HASH,
            "cribl_stream_tarball_base": "https://cdn.cribl.io/dl",
            "tofu_data": {
                "containers": {"s3": {"ip": "10.0.0.1"}},
                "constants": {"service_ports": {"object_storage_s3": 9000}},
            },
        }

    def _render(self, path: Path) -> str:
        template = _load_var(path, "cribl_stream_tarball_url")
        return self.env.from_string(template).render(**self.context)

    def test_cdn_default_url_carries_the_build_hash(self):
        url = self._render(DEFAULTS)
        expected_filename = f"cribl-{TEST_VERSION}-{TEST_HASH}-linux-x64.tgz"
        self.assertIn(
            expected_filename,
            url,
            f"CDN tarball URL {url!r} does not carry the build hash -- "
            "Cribl's real filenames always include one and a bare "
            "version-only filename 404s.",
        )

    def test_object_storage_mirror_url_carries_the_build_hash(self):
        url = self._render(GROUP_VARS)
        expected_filename = f"cribl-{TEST_VERSION}-{TEST_HASH}-linux-x64.tgz"
        self.assertIn(
            expected_filename,
            url,
            f"Object-storage mirror URL {url!r} does not carry the build "
            "hash -- a bare cribl-linux-x64.tgz key can silently stay "
            "pinned to whatever build was last uploaded there.",
        )

    def test_declared_sha256_is_a_real_sha256_shape(self):
        checksum = _load_var(DEFAULTS, "cribl_stream_tarball_sha256")
        self.assertRegex(
            checksum,
            r"^[0-9a-f]{64}$",
            "cribl_stream_tarball_sha256 must be a 64-character lowercase "
            "hex sha256 digest, exactly as the CDN's .sha256 sidecar prints "
            "it, or get_url's checksum verification is not actually "
            "checking the declared value.",
        )


if __name__ == "__main__":
    unittest.main()
