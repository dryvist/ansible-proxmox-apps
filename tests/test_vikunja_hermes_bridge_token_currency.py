"""A stored value that authenticates is still replaced when no token titled
`hermes-bridge-<user>` carries the declared permissions (an untitled seed or
drifted permissions), or when the id stored beside the value is not that
titled token's id (a token minted whose publish is absent or stale).

These render the REAL expressions out of the task file, never a
reimplementation.
"""

import unittest

from vikunja_hermes_task_support import (
    BRIDGE,
    CURRENT_TASK,
    FIND_TASK,
    IDENTITIES_REL,
    MINT_TASK,
    PUBLISH_TASK,
    RESOLVE_TASK,
    TITLED_ID,
    all_true,
    defaults,
    find,
    render_template,
    titled,
)


class FindTitledToken(unittest.TestCase):
    TASK = FIND_TASK

    def find(self, tokens):
        return render_template(
            find(self.TASK)["ansible.builtin.set_fact"]["vikunja_hermes_titled_token"],
            {
                "vikunja_hermes_token_list": {"json": tokens},
                "vikunja_hermes_identity": {"username": "hermes"},
            },
        )

    def test_picks_the_token_with_the_bridge_title(self):
        tokens = [
            {"id": 1, "title": "seed"},
            {"id": 2},
            titled(BRIDGE),
            {"id": 9, "title": "hermes-bridge-donna"},
        ]
        self.assertEqual(self.find(tokens)["id"], TITLED_ID)

    def test_no_titled_token_resolves_empty(self):
        self.assertEqual(self.find([{"id": 1, "title": "seed"}]), {})


class StoredTokenIsCurrent(unittest.TestCase):
    TASK = CURRENT_TASK

    def _facts(self, works, titled, declared=BRIDGE, stored_id=TITLED_ID):
        facts = find(self.TASK)["ansible.builtin.set_fact"]
        variables = {
            "vikunja_hermes_stored_token_works": works,
            "vikunja_hermes_stored_token_id": stored_id,
            "vikunja_hermes_titled_token": titled,
            "vikunja_hermes_identity": {"token_permissions": declared},
        }
        return {
            name: render_template(expr, variables) for name, expr in facts.items()
        }

    def _current(self, works, titled, declared=BRIDGE, stored_id=TITLED_ID):
        return self._facts(works, titled, declared, stored_id)["vikunja_hermes_token_current"]

    def test_minted_but_not_published_is_not_current(self):
        # The titled token exists and its permissions match, and the stored
        # value (a seed minted elsewhere) still authenticates, but no id was
        # ever published beside it.
        self.assertFalse(self._current(True, titled(BRIDGE), stored_id=""))

    def test_a_stale_stored_id_is_not_current(self):
        # A later mint replaced the titled token but its publish never landed.
        self.assertFalse(self._current(True, titled(BRIDGE), stored_id=TITLED_ID - 1))

    def test_a_stored_id_that_differs_only_in_type_is_current(self):
        # KV round-trips the id as a JSON number; compare by value.
        self.assertTrue(self._current(True, titled(BRIDGE), stored_id=str(TITLED_ID)))

    def test_matching_permissions_are_current(self):
        self.assertTrue(self._current(True, titled(BRIDGE)))

    def test_action_order_does_not_matter(self):
        shuffled = {
            "tasks": ["update", "read_one"],
            "projects": ["views_buckets_tasks", "read_all"],
        }
        self.assertTrue(self._current(True, titled(shuffled)))

    def test_permission_drift_is_not_current(self):
        # The declaration gained tasks.create; the minted token lacks it.
        declared = {**BRIDGE, "tasks": ["create", "read_one", "update"]}
        self.assertFalse(self._current(True, titled(BRIDGE), declared))

    def test_a_dropped_action_is_not_current(self):
        declared = {**BRIDGE, "tasks": ["read_one"]}
        self.assertFalse(self._current(True, titled(BRIDGE), declared))

    def test_an_untitled_stored_token_is_not_current(self):
        # The stored value authenticates but no hermes-bridge-<user> token
        # exists: a hand-seeded value is replaced.
        self.assertFalse(self._current(True, {}))

    def test_a_titled_match_whose_stored_value_is_refused_is_not_current(self):
        self.assertFalse(self._current(False, titled(BRIDGE)))

    def test_the_titled_token_id_is_recorded_for_deletion(self):
        self.assertEqual(
            self._facts(True, titled(BRIDGE))["vikunja_hermes_existing_token_id"], TITLED_ID
        )
        self.assertEqual(self._facts(True, {})["vikunja_hermes_existing_token_id"], "")


class ReMintDecision(unittest.TestCase):
    """The real expressions in task order: the stored OpenBao fields and the
    listed Vikunja tokens, through to the Mint `when` and the publish body."""

    PUBLISH = PUBLISH_TASK
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
            RESOLVE_TASK,
            FIND_TASK,
            CURRENT_TASK,
        ):
            for name, expr in find(task)["ansible.builtin.set_fact"].items():
                variables[name] = render_template(expr, variables)
        return variables

    def _mints(self, bao_data, tokens, **kwargs):
        return all_true(
            find(MINT_TASK)["when"],
            self._state(bao_data, tokens, **kwargs),
        )

    def _published(self, bao_data, tokens, minted):
        variables = self._state(bao_data, tokens)
        variables["vikunja_hermes_token_mint"] = {"json": minted}
        body = find(self.PUBLISH)["ansible.builtin.uri"]["body"]["data"]
        return render_template(body, variables)

    def _stored(self, token_id=TITLED_ID):
        return {self.FIELD: "tk_live", f"{self.FIELD}_ID": token_id}

    def test_permission_drift_re_mints(self):
        declared = {**BRIDGE, "tasks": ["create", "read_one", "update"]}
        self.assertTrue(self._mints(self._stored(), [titled(BRIDGE)], declared=declared))

    def test_matching_permissions_do_not_re_mint(self):
        self.assertFalse(self._mints(self._stored(), [titled(BRIDGE)]))

    def test_an_untitled_stored_token_re_mints(self):
        self.assertTrue(self._mints(self._stored(), [{"id": 3, "title": "seed"}]))

    def test_a_titled_token_minted_but_never_published_re_mints(self):
        # The stored value predates the mint and still authenticates; nothing
        # at the OpenBao path names the titled token.
        self.assertTrue(self._mints({self.FIELD: "tk_seed"}, [titled(BRIDGE)]))

    def test_a_stale_published_id_re_mints(self):
        self.assertTrue(self._mints(self._stored(TITLED_ID - 1), [titled(BRIDGE)]))

    def test_an_empty_openbao_path_re_mints(self):
        self.assertTrue(self._mints({}, [titled(BRIDGE)], works=False))

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
        self.assertFalse(self._mints(published, [titled(BRIDGE)]))


class SelectedIdentities(unittest.TestCase):
    SELECT = "Select the Hermes bridge identities to provision"
    ASSERT = "Assert the selected Hermes bridge usernames are declared identities"
    IDS = [{"username": "donna"}, {"username": "hermes"}]

    def _selected(self, usernames):
        fact = find(self.SELECT, IDENTITIES_REL)["ansible.builtin.set_fact"]
        return render_template(
            fact["vikunja_hermes_bridge_selected"],
            {
                "vikunja_hermes_bridge_identities": self.IDS,
                "vikunja_hermes_bridge_usernames": usernames,
            },
        )

    def _declared(self, usernames):
        that = find(self.ASSERT, IDENTITIES_REL)["ansible.builtin.assert"]["that"]
        return all_true(
            that,
            {
                "vikunja_hermes_bridge_identities": self.IDS,
                "vikunja_hermes_bridge_usernames": usernames,
            },
        )

    def test_the_default_selects_no_one_in_particular(self):
        self.assertEqual(defaults()["vikunja_hermes_bridge_usernames"], [])

    def test_an_empty_selection_provisions_every_identity(self):
        self.assertEqual(self._selected([]), self.IDS)

    def test_a_named_selection_provisions_only_that_identity(self):
        self.assertEqual(self._selected(["hermes"]), [{"username": "hermes"}])

    def test_a_declared_selection_passes_the_assert(self):
        self.assertTrue(self._declared(["hermes"]))
        self.assertTrue(self._declared([]))

    def test_an_undeclared_username_fails_the_assert(self):
        self.assertFalse(self._declared(["hermes", "nobody"]))

    def test_every_per_identity_loop_runs_over_the_selection(self):
        tasks = [
            "Resolve each identity's login password",
            "Create Hermes bridge Vikunja users (idempotent — skipped if already present)",
            "Provision each Hermes bridge identity's shares, token, and OpenBao publish",
        ]
        for name in tasks:
            loop = find(name, IDENTITIES_REL)["loop"]
            self.assertEqual(loop, "{{ vikunja_hermes_bridge_selected }}", name)


class HermesIdentityDeclaration(unittest.TestCase):
    def _identity(self, username):
        return next(
            item
            for item in defaults()["vikunja_hermes_bridge_identities"]
            if item["username"] == username
        )

    def _intake(self):
        return render_template(
            defaults()["vikunja_hermes_intake_permissions"],
            {
                "vikunja_hermes_bridge_permissions": defaults()[
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
        bridge = defaults()["vikunja_hermes_bridge_permissions"]
        intake = self._intake()
        for group, actions in bridge.items():
            self.assertLessEqual(set(actions), set(intake[group]), group)

    def test_hermes_is_shared_on_projects_64_and_55(self):
        shares = self._identity("hermes")["project_shares"]
        self.assertEqual({share["project_id"] for share in shares}, {64, 55})
        for share in shares:
            self.assertEqual(share["owner_username"], "svc-mcp-rw")
            self.assertEqual(share["permission"], 1)


if __name__ == "__main__":
    unittest.main()
