"""A Vikunja token titled `hermes-bridge-<user>` existing does not prove the
value stored at openbao_path still authenticates. Before this fix, "Mint API
token" skipped whenever a titled token existed, so a missing or refused
stored value was never replaced and "Publish the minted token to OpenBao"
then had nothing new to write — a clean recap with no real work done.

These render the REAL expressions out of the task file, never a
reimplementation.
"""

import re
import unittest

from vikunja_hermes_task_support import (
    MINT_TASK,
    RESOLVE_TASK,
    all_true,
    defaults,
    find,
    render_template,
)


class ResolveStoredToken(unittest.TestCase):
    TASK = RESOLVE_TASK

    def _resolve(self, bao_json):
        return render_template(
            find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token"],
            {
                "vikunja_hermes_bao_current": {"json": bao_json},
                "vikunja_hermes_identity": {"kv_field": "DONNA_VIKUNJA_API_TOKEN"},
            },
        )

    def test_the_field_missing_resolves_empty(self):
        # Today's real case: ai/donna holds other fields, never this one.
        self.assertEqual(self._resolve({"data": {"data": {"OTHER_FIELD": "x"}}}), "")

    def test_a_404_read_resolves_empty(self):
        self.assertEqual(self._resolve({"errors": []}), "")

    def _resolve_id(self, bao_json):
        return render_template(
            find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_id"],
            {
                "vikunja_hermes_bao_current": {"json": bao_json},
                "vikunja_hermes_identity": {"kv_field": "DONNA_VIKUNJA_API_TOKEN"},
            },
        )

    def test_the_id_field_resolves_from_the_sibling_key(self):
        data = {"DONNA_VIKUNJA_API_TOKEN": "tk_live", "DONNA_VIKUNJA_API_TOKEN_ID": 7}
        self.assertEqual(self._resolve_id({"data": {"data": data}}), 7)

    def test_a_missing_id_field_resolves_empty(self):
        data = {"DONNA_VIKUNJA_API_TOKEN": "tk_live"}
        self.assertEqual(self._resolve_id({"data": {"data": data}}), "")

    def test_the_field_present_resolves_its_value(self):
        self.assertEqual(
            self._resolve({"data": {"data": {"DONNA_VIKUNJA_API_TOKEN": "tk_live"}}}),
            "tk_live",
        )


class MintFiresOnAStaleToken(unittest.TestCase):
    TASK = MINT_TASK

    def _fires(self, token_current):
        return all_true(
            find(self.TASK)["when"],
            {"vikunja_hermes_token_current": token_current},
        )

    def test_mint_fires_when_the_token_is_not_current(self):
        self.assertTrue(self._fires(False))

    def test_mint_is_skipped_when_the_token_is_current(self):
        self.assertFalse(self._fires(True))


class RecordStoredTokenUsable(unittest.TestCase):
    TASK = (
        "Record whether the stored token is usable for "
        "{{ vikunja_hermes_identity.username }}"
    )

    def _works(self, check_result):
        return render_template(
            find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_works"],
            {"vikunja_hermes_stored_token_check": check_result},
        )

    def test_no_check_ran_is_not_usable(self):
        # vikunja_hermes_stored_token was empty, so "Verify the stored
        # token..." was skipped by its own `when` and never registered
        # a .status — this is today's real ai/donna case.
        self.assertFalse(self._works({}))

    def test_a_200_is_usable(self):
        self.assertTrue(self._works({"status": 200}))

    def test_a_401_is_not_usable(self):
        # Present but refused — a stale/foreign/revoked value.
        self.assertFalse(self._works({"status": 401}))


class DeleteStaleTokenOnlyWhenNeeded(unittest.TestCase):
    TASK = "Delete the stale API token for {{ vikunja_hermes_identity.username }}"

    def _fires(self, token_current, existing_token_id):
        return all_true(
            find(self.TASK)["when"],
            {
                "vikunja_hermes_token_current": token_current,
                "vikunja_hermes_existing_token_id": existing_token_id,
            },
        )

    def test_fires_when_not_current_and_a_titled_token_exists(self):
        self.assertTrue(self._fires(False, "42"))

    def test_does_not_fire_when_the_token_is_current(self):
        self.assertFalse(self._fires(True, "42"))

    def test_does_not_fire_when_there_is_nothing_to_delete(self):
        self.assertFalse(self._fires(False, ""))

    def test_fires_with_a_real_int_token_id_not_just_a_string(self):
        # Vikunja's token id is a JSON integer; `first | default('', true)`
        # on the parsed list yields that int (Ansible's own tagged int
        # subclass in real runs), never a string. The other cases above
        # only ever pass a string, which let a `| length > 0` guard on a
        # bare int ship without being caught.
        self.assertTrue(self._fires(False, 42))


class TokenListIsAlwaysFetched(unittest.TestCase):
    def test_listing_is_not_gated_on_the_stored_token(self):
        # Permission drift is only visible on the list, and the stored token
        # authenticating says nothing about it.
        task = find("List existing API tokens for {{ vikunja_hermes_identity.username }}")
        self.assertNotIn("when", task)


class ProbeEndpointStaysInScope(unittest.TestCase):
    """A stored token only ever holds the permissions
    vikunja_hermes_bridge_permissions grants (projects/tasks scopes, never
    `user`), so the liveness probe must hit a route inside that same set --
    otherwise a freshly-minted, fully working token reads 401/403 forever
    and the check can never report success. Derived from the real
    permissions var, not a hardcoded group name, so it breaks the moment
    the probe and the granted scopes drift apart again in either
    direction.
    """

    TASK = "Verify the stored token still authenticates for {{ vikunja_hermes_identity.username }}"

    def test_probe_path_is_a_granted_permission_group(self):
        url = find(self.TASK)["ansible.builtin.uri"]["url"]
        match = re.search(r"/api/v1/([a-z_]+)", url)
        assert match is not None, f"no /api/v1/<group> path in {url!r}"
        group = match.group(1)
        permissions = defaults()["vikunja_hermes_bridge_permissions"]
        self.assertIn(
            group,
            permissions,
            f"probe hits {group!r}, which vikunja_hermes_bridge_permissions "
            f"does not grant: {sorted(permissions)}",
        )
        self.assertTrue(
            permissions[group],
            f"{group!r} is granted but with no actions: {permissions[group]!r}",
        )


if __name__ == "__main__":
    unittest.main()
