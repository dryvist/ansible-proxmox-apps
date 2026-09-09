#!/usr/bin/env python3
"""There are two ways to be the reconcile identity, and exactly one may fire.

An unattended converge reconciles policies, AppRoles, TTL bounds and generated
application secrets only if it can act as the reconcile identity. It can do that
two ways:

  * a pre-issued token that already carries the policy, maintained by an agent
    on the host -- the intended shape for an unattended plane, because the
    converge then never holds a secret_id at all;
  * secret-zero in the environment, which the workstation path uses.

The execution plane had NEITHER. Every routine converge skipped the whole
provisioning path and still reported success: 66 policies, every AppRole and 13
generated-secret apps untouched for three days, behind a green recap.

These assertions cover the gating, because the failure mode is silence and
silence is what a recap cannot show:

  1. Exactly one credential path fires for any given environment. A host
     carrying both must not mint a second credential it would then have to
     revoke.
  2. A provisioning token still wins over both, and turns OFF the
     least-privilege filter -- that is its whole purpose.
  3. With neither, both paths stay off so the loud skip is what speaks.
  4. The login keeps its failure reason, and the failure message repeats it.
"""

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

TASKS = (
    Path(__file__).resolve().parent.parent
    / "roles" / "openbao" / "tasks" / "init" / "02-initialize-cluster.yml"
)

TOKEN_PATH = "Use the pre-issued reconcile token when one is supplied"
LOGIN = "Log in as the reconcile identity for routine RBAC reconciliation"
FAILED_LOGIN = "FAIL — the reconcile identity was configured but could not authenticate"

# The environments a converge actually runs in.
PLANE_WITH_AGENT = dict(
    openbao_provisioning_token="", openbao_reconcile_token="tok",
    openbao_reconcile_role_id="", openbao_reconcile_secret_id="",
    openbao_reconcile_addr="https://store.invalid",
)
WORKSTATION = dict(
    openbao_provisioning_token="", openbao_reconcile_token="",
    openbao_reconcile_role_id="rid", openbao_reconcile_secret_id="sid",
    openbao_reconcile_addr="https://store.invalid",
)
BOTH = dict(
    openbao_provisioning_token="", openbao_reconcile_token="tok",
    openbao_reconcile_role_id="rid", openbao_reconcile_secret_id="sid",
    openbao_reconcile_addr="https://store.invalid",
)
PRIVILEGED = dict(
    openbao_provisioning_token="ptok", openbao_reconcile_token="tok",
    openbao_reconcile_role_id="rid", openbao_reconcile_secret_id="sid",
    openbao_reconcile_addr="https://store.invalid",
)
NEITHER = dict(
    openbao_provisioning_token="", openbao_reconcile_token="",
    openbao_reconcile_role_id="", openbao_reconcile_secret_id="",
    openbao_reconcile_addr="https://store.invalid",
)

INITIALIZED = {"openbao_status": {"initialized": True}}


def _tasks(node):
    if isinstance(node, list):
        for entry in node:
            yield from _tasks(entry)
    elif isinstance(node, dict):
        if "name" in node:
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _tasks(node[key])


class ReconcileIdentityPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = {t["name"]: t for t in _tasks(yaml.safe_load(TASKS.read_text()))}
        for name in (TOKEN_PATH, LOGIN, FAILED_LOGIN):
            assert name in cls.tasks, f"{name!r} not found in {TASKS}"
        cls.env = Environment()
        cls.env.filters["bool"] = lambda v: str(v).strip().lower() in (
            "true", "yes", "on", "1"
        )

    def _fires(self, task_name, environment):
        conds = self.tasks[task_name]["when"]
        if isinstance(conds, str):
            conds = [conds]
        context = {**INITIALIZED, **environment}
        for cond in conds:
            rendered = self.env.from_string("{{ %s }}" % cond).render(**context)
            if rendered.strip() != "True":
                return False
        return True

    def test_the_plane_uses_its_token_and_does_not_log_in(self):
        self.assertTrue(self._fires(TOKEN_PATH, PLANE_WITH_AGENT))
        self.assertFalse(self._fires(LOGIN, PLANE_WITH_AGENT))

    def test_the_workstation_still_logs_in(self):
        self.assertFalse(self._fires(TOKEN_PATH, WORKSTATION))
        self.assertTrue(self._fires(LOGIN, WORKSTATION))

    def test_a_host_carrying_both_mints_nothing_extra(self):
        # Two credentials for one run means one of them is issued and never
        # revoked. The token wins because whatever supplies it maintains it.
        self.assertTrue(self._fires(TOKEN_PATH, BOTH))
        self.assertFalse(self._fires(LOGIN, BOTH))

    def test_a_provisioning_token_suppresses_both(self):
        self.assertFalse(self._fires(TOKEN_PATH, PRIVILEGED))
        self.assertFalse(self._fires(LOGIN, PRIVILEGED))

    def test_with_neither_credential_nothing_fires(self):
        # This is the state the plane was in. Both paths off, so the loud skip
        # is the only thing that speaks -- and it must not be reachable by a
        # path that silently succeeded.
        self.assertFalse(self._fires(TOKEN_PATH, NEITHER))
        self.assertFalse(self._fires(LOGIN, NEITHER))

    def test_the_login_keeps_its_failure_reason(self):
        login = self.tasks[LOGIN]
        self.assertTrue(login.get("ignore_errors"))
        self.assertNotIn("failed_when", login)

    def test_the_failure_repeats_what_the_store_said(self):
        msg = self.tasks[FAILED_LOGIN]["ansible.builtin.fail"]["msg"]
        self.assertIn("openbao_reconcile_login.msg", msg)


if __name__ == "__main__":
    unittest.main()
