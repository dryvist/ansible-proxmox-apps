"""The Hermes bridge token probe must run for real, and refuse a write probe
that creates an object.

A PUT probe with an empty title is expected to be rejected with a 4xx, which
proves the token authenticated without creating anything. These render the
REAL expressions out of the task file, never a reimplementation.
"""

import unittest

from vikunja_hermes_task_support import all_true, find, render_template

PROBE = "Verify the stored token still authenticates for {{ vikunja_hermes_identity.username }}"
RECORD = "Record whether the stored token is usable for {{ vikunja_hermes_identity.username }}"
GUARD = "Refuse a token probe that created an object for {{ vikunja_hermes_identity.username }}"

AI_JOBS = {
    "username": "ai_jobs",
    "probe": {"method": "PUT", "authenticated_statuses": [400, 403]},
}
GET_ONLY = {"username": "hermes"}


def variables(identity, status=None, json=None, token="tk_live"):
    check = {} if status is None else {"status": status, "json": json or {}}
    return {
        "vikunja_hermes_identity": identity,
        "vikunja_hermes_stored_token": token,
        "vikunja_hermes_stored_token_check": check,
    }


class ProbeRunsForReal(unittest.TestCase):
    def test_the_probe_is_not_forced_into_a_check_mode_skip(self):
        # uri does not support check mode, so a forced skip read as unusable.
        self.assertIs(find(PROBE)["check_mode"], False)


class RecordAuthenticatedStatuses(unittest.TestCase):
    def _works(self, identity, status):
        expr = find(RECORD)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_works"]
        return render_template(expr, variables(identity, status))

    def test_the_write_probes_400_means_authenticated(self):
        self.assertTrue(self._works(AI_JOBS, 400))

    def test_the_write_probes_403_also_means_authenticated(self):
        self.assertTrue(self._works(AI_JOBS, 403))

    def test_a_created_object_is_not_proof_of_a_usable_token(self):
        self.assertFalse(self._works(AI_JOBS, 201))


class RefuseCreatingProbe(unittest.TestCase):
    def _fires(self, identity, status, json=None, token="tk_live"):
        return all_true(find(GUARD)["when"], variables(identity, status, json, token))

    def test_a_201_from_the_write_probe_is_refused(self):
        self.assertTrue(self._fires(AI_JOBS, 201, {"id": 77}))

    def test_a_200_from_the_write_probe_is_refused(self):
        self.assertTrue(self._fires(AI_JOBS, 200))

    def test_the_400_path_is_not_refused(self):
        self.assertFalse(self._fires(AI_JOBS, 400))

    def test_the_403_path_is_not_refused(self):
        self.assertFalse(self._fires(AI_JOBS, 403))

    def test_a_get_probe_that_returns_200_is_not_refused(self):
        self.assertFalse(self._fires(GET_ONLY, 200))

    def test_an_identity_without_a_probe_key_is_not_refused(self):
        self.assertFalse(self._fires(GET_ONLY, 401))

    def test_nothing_is_refused_when_no_stored_token_was_probed(self):
        self.assertFalse(self._fires(AI_JOBS, None, token=""))


if __name__ == "__main__":
    unittest.main()
