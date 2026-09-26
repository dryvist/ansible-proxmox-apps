"""A Renovate-tracked version must never sit next to a static checksum pin.

The trap: a role default pins `<x>_version` with a
`# renovate: datasource=...` comment (so Renovate bumps it automatically) and
also pins a static `<x>_sha256`/`<x>_checksum` for the same download next to
it. Renovate updates the version on its own schedule; the hash is never part
of that PR, so the two silently desync the first time the version moves. The
download then fails at `get_url`'s checksum mismatch on every future converge,
with no signal until something tries to run it.

This broke authelia in 2026-09: Renovate bumped authelia_version 4.39.22 ->
4.39.27 and left `authelia_release_tgz_sha256` pointing at the old tarball's
hash. The fix (roles/authelia/tasks/main.yml) reads the expected hash from
Authelia's own signed release manifest at converge time instead of freezing
one in defaults -- the manifest can't go stale because it always describes
the version currently being downloaded.

This test stops the pattern from spreading. It does not retroactively fix the
other roles that already have it -- those are pre-existing debt, tracked in
KNOWN_OFFENDERS. Fixing one: drop it from KNOWN_OFFENDERS in the same PR that
removes the static pin, the same way this PR does for authelia.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RENOVATE_COMMENT_RE = re.compile(r"^\s*#\s*renovate:\s*datasource=", re.MULTILINE)
STATIC_CHECKSUM_RE = re.compile(
    r"^[^#\n]*_(?:sha256|checksum)\s*:\s*[\"']?[0-9a-f]{64}",
    re.MULTILINE | re.IGNORECASE,
)

# Pre-existing debt: a role default already pairs a renovate-tracked version
# with a static checksum for the same artifact. Not fixed here -- tracked
# separately. Remove an entry only in the same PR that removes its static pin.
KNOWN_OFFENDERS = frozenset(
    {
        "roles/glance/defaults/main.yml",
        "roles/object_storage/defaults/main/00-core.yml",
        "roles/technitium_install/defaults/main.yml",
        "roles/vikunja/defaults/main.yml",
    }
)


def _default_files():
    yield from ROOT.glob("roles/*/defaults/main.yml")
    yield from ROOT.glob("roles/*/defaults/main/*.yml")


class NoNewRenovateChecksumDrift(unittest.TestCase):
    def test_no_new_offenders(self):
        hits = set()
        for path in _default_files():
            text = path.read_text()
            if RENOVATE_COMMENT_RE.search(text) and STATIC_CHECKSUM_RE.search(text):
                hits.add(str(path.relative_to(ROOT)))

        new_hits = hits - KNOWN_OFFENDERS
        self.assertEqual(
            set(),
            new_hits,
            "Renovate-tracked version pinned next to a static checksum in: "
            "%s. Renovate bumps the version without touching the checksum, "
            "so every converge fails at the download's checksum mismatch the "
            "moment the version moves (this is what broke authelia in "
            "2026-09). Verify the checksum from the vendor's own signed "
            "release manifest at converge time instead -- see "
            "roles/authelia/tasks/main.yml for the pattern."
            % sorted(new_hits),
        )

        stale = KNOWN_OFFENDERS - hits
        self.assertEqual(
            set(),
            stale,
            "KNOWN_OFFENDERS lists %s but it no longer has the drift pattern "
            "-- remove it from the allowlist." % sorted(stale),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)
