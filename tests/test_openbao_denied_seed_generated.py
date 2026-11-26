"""A denied read must not mint fresh values over live credentials.

Checked against the shared dryvist.homelab.openbao_secrets seed_generated.yml,
which the app-secret seeding calls. Its stored-secret read is a uri task, and the
local-values fallback block it routes to must never write to OpenBao.
"""

import unittest

from secrets_collection_support import HOMELAB_ROLES
from test_openbao_denied_vs_absent_writes import (
    _all,
    _find,
    _writes_to_openbao,
)


class SeedGeneratedAppSecret(unittest.TestCase):
    """A denied read must not mint fresh values over live credentials."""

    REL = HOMELAB_ROLES / "openbao_secrets/tasks/seed_generated.yml"
    READ = "Read the stored secret and its version"
    ROUTE = "Return local values when OpenBao is unavailable"

    def _read_fails(self, status):
        # ansible.builtin.uri fails the task for any status outside status_code.
        return status not in _find(self.REL, self.READ)["ansible.builtin.uri"]["status_code"]

    def test_a_DENIED_read_fails_the_task(self):
        # The one that matters. A 403 must fail the run, never collapse to "unset".
        self.assertTrue(self._read_fails(403))

    def test_a_genuinely_absent_path_does_NOT_fail(self):
        # Generate-if-absent must still work on a first converge.
        self.assertFalse(self._read_fails(404))

    def test_a_successful_read_does_NOT_fail(self):
        # Exactly [200, 404], so a 500 or any other status still fails the read.
        self.assertEqual(_find(self.REL, self.READ)["ansible.builtin.uri"]["status_code"], [200, 404])
        self.assertFalse(self._read_fails(200))
        self.assertTrue(self._read_fails(500))

    def test_an_unreachable_server_routes_to_local_values_and_never_writes(self):
        # The health gate sends an unavailable OpenBao to the local-values block, which must not write.
        route = _find(self.REL, self.ROUTE)
        self.assertTrue(route["block"], "the local-values block has no tasks to check")
        self.assertTrue(_all(route["when"], {"openbao_secrets_seed_available": False}))
        self.assertFalse(_all(route["when"], {"openbao_secrets_seed_available": True}))
        self.assertEqual(_writes_to_openbao(route["block"]), [])
