"""A Vikunja token titled `hermes-bridge-<user>` existing does not prove the
value stored at openbao_path still authenticates. Before this fix, "Mint API
token" skipped whenever a titled token existed, so a missing or refused
stored value was never replaced and "Publish the minted token to OpenBao"
then had nothing new to write — a clean recap with no real work done.

These render the REAL expressions out of the task file, never a
reimplementation.
"""

from pathlib import Path
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
REL = "roles/vikunja/tasks/hermes_bridge_identity_one.yml"


def _tasks():
    return yaml.safe_load((ROOT / REL).read_text(encoding="utf-8"))


def _find(name):
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"task {name!r} not found in {REL}")


def _render(expr, variables):
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template("{{ " + expr + " }}"))


def _render_template(text, variables):
    """Render a set_fact value: already a full `{{ ... }}` string in the
    source, unlike a bare `when`/`failed_when` condition — do not re-wrap."""
    templar = Templar(loader=DataLoader())
    templar.available_variables = variables
    return templar.template(trust_as_template(text))


def _all(conds, variables):
    if not isinstance(conds, list):
        conds = [conds]
    return all(
        c if isinstance(c, bool) else bool(_render(c, variables)) for c in conds
    )


class ResolveStoredToken(unittest.TestCase):
    TASK = "Resolve the stored token for {{ vikunja_hermes_identity.username }}"

    def _resolve(self, bao_json):
        return _render_template(
            _find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token"],
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

    def test_the_field_present_resolves_its_value(self):
        self.assertEqual(
            self._resolve({"data": {"data": {"DONNA_VIKUNJA_API_TOKEN": "tk_live"}}}),
            "tk_live",
        )


class MintFiresOnAnUnusableStoredToken(unittest.TestCase):
    TASK = "Mint API token for {{ vikunja_hermes_identity.username }}"

    def _fires(self, stored_token_works):
        return _all(
            _find(self.TASK)["when"],
            {"vikunja_hermes_stored_token_works": stored_token_works},
        )

    def test_mint_fires_when_the_stored_token_does_not_authenticate(self):
        # The exact defect: a titled token existing must not matter here —
        # only whether the STORED value at openbao_path works.
        self.assertTrue(self._fires(False))

    def test_mint_is_skipped_when_the_stored_token_authenticates(self):
        self.assertFalse(self._fires(True))


class RecordStoredTokenUsable(unittest.TestCase):
    TASK = (
        "Record whether the stored token is usable for "
        "{{ vikunja_hermes_identity.username }}"
    )

    def _works(self, check_result):
        return _render_template(
            _find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_works"],
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

    def _fires(self, stored_token_works, existing_token_id):
        return _all(
            _find(self.TASK)["when"],
            {
                "vikunja_hermes_stored_token_works": stored_token_works,
                "vikunja_hermes_existing_token_id": existing_token_id,
            },
        )

    def test_fires_when_unusable_and_a_titled_token_exists(self):
        self.assertTrue(self._fires(False, "42"))

    def test_does_not_fire_when_the_stored_token_still_works(self):
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


if __name__ == "__main__":
    unittest.main()
