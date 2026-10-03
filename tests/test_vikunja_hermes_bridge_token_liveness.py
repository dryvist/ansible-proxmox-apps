"""A Vikunja token titled `hermes-bridge-<user>` existing does not prove the
value stored at openbao_path still authenticates. Before this fix, "Mint API
token" skipped whenever a titled token existed, so a missing or refused
stored value was never replaced and "Publish the minted token to OpenBao"
then had nothing new to write — a clean recap with no real work done.

A stored value that authenticates is still replaced when no token titled
`hermes-bridge-<user>` carries the declared permissions (an untitled seed, or
permissions that drifted from the declaration, or a titled token minted but
never published, whose id is not the one stored beside the value).

These render the REAL expressions out of the task file, never a
reimplementation.
"""

from pathlib import Path
import re
import unittest

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

ROOT = Path(__file__).resolve().parents[1]
REL = "roles/vikunja/tasks/hermes_bridge_identity_one.yml"
DEFAULTS_REL = "roles/vikunja/defaults/main.yml"


def _tasks():
    return yaml.safe_load((ROOT / REL).read_text(encoding="utf-8"))


def _defaults():
    return yaml.safe_load((ROOT / DEFAULTS_REL).read_text(encoding="utf-8"))


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

    def _resolve_id(self, bao_json):
        return _render_template(
            _find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_stored_token_id"],
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
    TASK = "Mint API token for {{ vikunja_hermes_identity.username }}"

    def _fires(self, token_current):
        return _all(
            _find(self.TASK)["when"],
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

    def _fires(self, token_current, existing_token_id):
        return _all(
            _find(self.TASK)["when"],
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
        task = _find("List existing API tokens for {{ vikunja_hermes_identity.username }}")
        self.assertNotIn("when", task)


BRIDGE = {
    "projects": ["read_all", "views_buckets_tasks"],
    "tasks": ["read_one", "update"],
}


TITLED_ID = 7


def _titled(permissions, title="hermes-bridge-hermes"):
    return {"id": TITLED_ID, "title": title, "permissions": permissions}


class FindTitledToken(unittest.TestCase):
    TASK = "Find the existing titled token for {{ vikunja_hermes_identity.username }}"

    def _find(self, tokens):
        return _render_template(
            _find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_titled_token"],
            {
                "vikunja_hermes_token_list": {"json": tokens},
                "vikunja_hermes_identity": {"username": "hermes"},
            },
        )

    def test_picks_the_token_with_the_bridge_title(self):
        tokens = [
            {"id": 1, "title": "seed"},
            {"id": 2},
            _titled(BRIDGE),
            {"id": 9, "title": "hermes-bridge-donna"},
        ]
        self.assertEqual(self._find(tokens)["id"], TITLED_ID)

    def test_no_titled_token_resolves_empty(self):
        self.assertEqual(self._find([{"id": 1, "title": "seed"}]), {})


class StoredTokenIsCurrent(unittest.TestCase):
    TASK = "Record whether the stored token is current for {{ vikunja_hermes_identity.username }}"

    def _facts(self, works, titled, declared=BRIDGE, stored_id=TITLED_ID):
        facts = _find(self.TASK)["ansible.builtin.set_fact"]
        variables = {
            "vikunja_hermes_stored_token_works": works,
            "vikunja_hermes_stored_token_id": stored_id,
            "vikunja_hermes_titled_token": titled,
            "vikunja_hermes_identity": {"token_permissions": declared},
        }
        return {
            name: _render_template(expr, variables) for name, expr in facts.items()
        }

    def _current(self, works, titled, declared=BRIDGE, stored_id=TITLED_ID):
        return self._facts(works, titled, declared, stored_id)["vikunja_hermes_token_current"]

    def test_minted_but_not_published_is_not_current(self):
        # The titled token exists and its permissions match, and the stored
        # value (a seed minted elsewhere) still authenticates, but no id was
        # ever published beside it.
        self.assertFalse(self._current(True, _titled(BRIDGE), stored_id=""))

    def test_a_stale_stored_id_is_not_current(self):
        # A later mint replaced the titled token but its publish never landed.
        self.assertFalse(self._current(True, _titled(BRIDGE), stored_id=TITLED_ID - 1))

    def test_a_stored_id_that_differs_only_in_type_is_current(self):
        # KV round-trips the id as a JSON number; compare by value.
        self.assertTrue(self._current(True, _titled(BRIDGE), stored_id=str(TITLED_ID)))

    def test_matching_permissions_are_current(self):
        self.assertTrue(self._current(True, _titled(BRIDGE)))

    def test_action_order_does_not_matter(self):
        shuffled = {
            "tasks": ["update", "read_one"],
            "projects": ["views_buckets_tasks", "read_all"],
        }
        self.assertTrue(self._current(True, _titled(shuffled)))

    def test_permission_drift_is_not_current(self):
        # The declaration gained tasks.create; the minted token lacks it.
        declared = {**BRIDGE, "tasks": ["create", "read_one", "update"]}
        self.assertFalse(self._current(True, _titled(BRIDGE), declared))

    def test_a_dropped_action_is_not_current(self):
        declared = {**BRIDGE, "tasks": ["read_one"]}
        self.assertFalse(self._current(True, _titled(BRIDGE), declared))

    def test_an_untitled_stored_token_is_not_current(self):
        # The stored value authenticates but no hermes-bridge-<user> token
        # exists: a hand-seeded value is replaced.
        self.assertFalse(self._current(True, {}))

    def test_a_titled_match_whose_stored_value_is_refused_is_not_current(self):
        self.assertFalse(self._current(False, _titled(BRIDGE)))

    def test_the_titled_token_id_is_recorded_for_deletion(self):
        self.assertEqual(
            self._facts(True, _titled(BRIDGE))["vikunja_hermes_existing_token_id"], TITLED_ID
        )
        self.assertEqual(self._facts(True, {})["vikunja_hermes_existing_token_id"], "")


class ReMintDecision(unittest.TestCase):
    """The real expressions in task order: the stored OpenBao fields and the
    listed Vikunja tokens, through to the Mint `when` and the publish body."""

    PUBLISH = "Publish the minted token to OpenBao for {{ vikunja_hermes_identity.username }}"
    FIELD = "HERMES_VIKUNJA_API_TOKEN"

    def _state(self, bao_data, tokens, works=True, declared=BRIDGE):
        variables = {
            "vikunja_hermes_identity": {
                "username": "hermes",
                "kv_field": self.FIELD,
                "token_permissions": declared,
            },
            "vikunja_hermes_bao_current": {"json": {"data": {"data": bao_data}}},
            "vikunja_hermes_token_list": {"json": tokens},
            "vikunja_hermes_stored_token_works": works,
        }
        for task in (
            ResolveStoredToken.TASK,
            FindTitledToken.TASK,
            StoredTokenIsCurrent.TASK,
        ):
            for name, expr in _find(task)["ansible.builtin.set_fact"].items():
                variables[name] = _render_template(expr, variables)
        return variables

    def _mints(self, bao_data, tokens, **kwargs):
        return _all(
            _find(MintFiresOnAStaleToken.TASK)["when"],
            self._state(bao_data, tokens, **kwargs),
        )

    def _published(self, bao_data, tokens, minted):
        variables = self._state(bao_data, tokens)
        variables["vikunja_hermes_token_mint"] = {"json": minted}
        body = _find(self.PUBLISH)["ansible.builtin.uri"]["body"]["data"]
        return _render_template(body, variables)

    def _stored(self, token_id=TITLED_ID):
        return {self.FIELD: "tk_live", f"{self.FIELD}_ID": token_id}

    def test_permission_drift_re_mints(self):
        declared = {**BRIDGE, "tasks": ["create", "read_one", "update"]}
        self.assertTrue(self._mints(self._stored(), [_titled(BRIDGE)], declared=declared))

    def test_matching_permissions_do_not_re_mint(self):
        self.assertFalse(self._mints(self._stored(), [_titled(BRIDGE)]))

    def test_an_untitled_stored_token_re_mints(self):
        self.assertTrue(self._mints(self._stored(), [{"id": 3, "title": "seed"}]))

    def test_a_titled_token_minted_but_never_published_re_mints(self):
        # The stored value predates the mint and still authenticates; nothing
        # at the OpenBao path names the titled token.
        self.assertTrue(self._mints({self.FIELD: "tk_seed"}, [_titled(BRIDGE)]))

    def test_a_stale_published_id_re_mints(self):
        self.assertTrue(self._mints(self._stored(TITLED_ID - 1), [_titled(BRIDGE)]))

    def test_an_empty_openbao_path_re_mints(self):
        self.assertTrue(self._mints({}, [_titled(BRIDGE)], works=False))

    def test_the_publish_records_the_token_and_its_id_and_keeps_siblings(self):
        published = self._published(
            {"OTHER_FIELD": "keep"}, [], {"token": "tk_new", "id": 9}
        )
        self.assertEqual(
            published,
            {"OTHER_FIELD": "keep", self.FIELD: "tk_new", f"{self.FIELD}_ID": 9},
        )

    def test_a_published_state_is_stable_on_the_next_run(self):
        published = self._published({}, [], {"token": "tk_new", "id": TITLED_ID})
        self.assertFalse(self._mints(published, [_titled(BRIDGE)]))


class HermesIdentityDeclaration(unittest.TestCase):
    def _identity(self, username):
        return next(
            item
            for item in _defaults()["vikunja_hermes_bridge_identities"]
            if item["username"] == username
        )

    def _intake(self):
        return _render_template(
            _defaults()["vikunja_hermes_intake_permissions"],
            {
                "vikunja_hermes_bridge_permissions": _defaults()[
                    "vikunja_hermes_bridge_permissions"
                ]
            },
        )

    def test_hermes_publishes_to_its_own_field(self):
        identity = self._identity("hermes")
        self.assertEqual(identity["openbao_mount"], "secret")
        self.assertEqual(identity["openbao_path"], "ai/hermes")
        self.assertEqual(identity["kv_field"], "HERMES_VIKUNJA_API_TOKEN")

    def test_hermes_token_uses_the_intake_permissions(self):
        self.assertEqual(
            self._identity("hermes")["token_permissions"],
            "{{ vikunja_hermes_intake_permissions }}",
        )

    def test_intake_permissions_include_task_creation(self):
        self.assertIn("create", self._intake()["tasks"])

    def test_intake_permissions_extend_the_bridge_table(self):
        bridge = _defaults()["vikunja_hermes_bridge_permissions"]
        intake = self._intake()
        for group, actions in bridge.items():
            self.assertLessEqual(set(actions), set(intake[group]), group)

    def test_hermes_is_shared_on_projects_64_and_55(self):
        shares = self._identity("hermes")["project_shares"]
        self.assertEqual({share["project_id"] for share in shares}, {64, 55})
        for share in shares:
            self.assertEqual(share["owner_username"], "svc-mcp-rw")
            self.assertEqual(share["permission"], 1)


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
        url = _find(self.TASK)["ansible.builtin.uri"]["url"]
        match = re.search(r"/api/v1/([a-z_]+)", url)
        assert match is not None, f"no /api/v1/<group> path in {url!r}"
        group = match.group(1)
        permissions = _defaults()["vikunja_hermes_bridge_permissions"]
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
