#!/usr/bin/env python3
"""Reconcile authentication prefers maintained tokens, then per-call issuance.

An unattended converge reconciles policies, AppRoles, TTL bounds and generated
application secrets only if it can act as the reconcile identity. It can do that
two ways:

  * a pre-issued token that already carries the policy, maintained by an agent
    on the host -- the intended shape for an unattended plane, because the
    converge then never holds a secret_id at all;
  * one fresh secret_id from approle-issuer for each workstation run;
  * the old workstation OPENBAO_APPROLE_OPENBAO_RECONCILE_* pair is not read.

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
REPO = Path(__file__).resolve().parent.parent

TOKEN_PATH = "Use the pre-issued reconcile token when one is supplied"
ISSUER_LOGIN = "Mint a per-call reconcile token through the AppRole issuer"
ISSUER_TOKEN_PATH = "Use the per-call reconcile token when it authenticated"
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
    openbao_reconcile_role_id="", openbao_reconcile_secret_id="",
    openbao_reconcile_addr="https://store.invalid",
    openbao_reconcile_issuer_available=True,
    openbao_converge_role_id="", openbao_converge_secret_id="",
    openbao_reconcile_issuer_login={"skipped": False, "rc": 0, "stdout": "fixture-token"},
)
WORKSTATION_CONVERGE_PAIR = dict(
    openbao_provisioning_token="", openbao_reconcile_token="",
    openbao_reconcile_role_id="plane-role", openbao_reconcile_secret_id="plane-secret",
    openbao_reconcile_addr="https://store.invalid",
    openbao_reconcile_issuer_available=False,
    openbao_converge_role_id="plane-role", openbao_converge_secret_id="plane-secret",
    openbao_reconcile_issuer_login={"skipped": True},
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
        for name in (TOKEN_PATH, ISSUER_LOGIN, ISSUER_TOKEN_PATH, LOGIN, FAILED_LOGIN):
            assert name in cls.tasks, f"{name!r} not found in {TASKS}"
        cls.env = Environment()
        cls.env.filters["bool"] = lambda v: str(v).strip().lower() in (
            "true", "yes", "on", "1"
        )

    def _fires(self, task_name, environment):
        conds = self.tasks[task_name]["when"]
        if isinstance(conds, str):
            conds = [conds]
        context = {
            **INITIALIZED,
            "openbao_converge_role_id": "",
            "openbao_converge_secret_id": "",
            "openbao_reconcile_issuer_available": False,
            "openbao_reconcile_issuer_login": {"skipped": True, "rc": 1, "stdout": ""},
            **environment,
        }
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
        self.assertTrue(self._fires(ISSUER_LOGIN, WORKSTATION))
        self.assertTrue(self._fires(ISSUER_TOKEN_PATH, WORKSTATION))
        self.assertFalse(self._fires(LOGIN, WORKSTATION))

    def test_the_stored_reconcile_pair_is_not_read(self):
        defaults = REPO / "roles" / "openbao" / "defaults" / "main" / "08a-admin-and-ttls.yml"
        content = defaults.read_text()
        self.assertNotIn(
            "lookup('env', 'OPENBAO_APPROLE_OPENBAO_RECONCILE_ROLE_ID')",
            content,
        )
        self.assertNotIn(
            "lookup('env', 'OPENBAO_APPROLE_OPENBAO_RECONCILE_SECRET_ID')",
            content,
        )
        self.assertIn("lookup('env', 'CONVERGE_ROLE_ID')", content)
        self.assertIn("lookup('env', 'CONVERGE_SECRET_ID')", content)

    def test_only_the_execution_plane_converge_pair_is_a_direct_login(self):
        self.assertFalse(self._fires(ISSUER_LOGIN, WORKSTATION_CONVERGE_PAIR))
        self.assertTrue(self._fires(LOGIN, WORKSTATION_CONVERGE_PAIR))

    def test_the_issuer_token_must_come_from_issuer_credentials(self):
        defaults = REPO / "roles" / "openbao" / "defaults" / "main" / "08a-admin-and-ttls.yml"
        block = defaults.read_text().split("openbao_reconcile_issuer_available:", 1)[1]
        self.assertNotIn("BAO_TOKEN", block.split("\n\n", 1)[0])
        self.assertIn("OPENBAO_APPROLE_APPROLE_ISSUER_SECRET_ID", block)

    def test_the_issuer_can_revoke_each_minted_secret_id_by_accessor(self):
        policy = (REPO / "roles" / "openbao" / "templates" / "approle-issuer-policy.hcl.j2").read_text()
        self.assertIn(
            'path "auth/approle/role/{{ approle_name }}/secret-id-accessor/destroy"',
            policy,
        )
        self.assertIn('capabilities = ["update"]', policy)

    def test_runner_warning_uses_only_reconcile_credentials(self):
        runner = (REPO / "scripts" / "run-ansible.sh").read_text()
        warning = runner.split(
            "# BAO_TOKEN is the runner's SSH-signing token, not a reconcile credential.",
            1,
        )[1].split("then", 1)[0]
        self.assertIn("OPENBAO_PROVISIONING_TOKEN", warning)
        self.assertIn("OPENBAO_RECONCILE_TOKEN", warning)
        self.assertIn("CONVERGE_ROLE_ID", warning)
        self.assertIn("OPENBAO_APPROLE_APPROLE_ISSUER_ROLE_ID", warning)
        self.assertNotIn("BAO_TOKEN:-", warning)

    def test_a_host_carrying_both_mints_nothing_extra(self):
        # Two credentials for one run means one of them is issued and never
        # revoked. The token wins because whatever supplies it maintains it.
        self.assertTrue(self._fires(TOKEN_PATH, BOTH))
        self.assertFalse(self._fires(ISSUER_LOGIN, BOTH))
        self.assertFalse(self._fires(LOGIN, BOTH))

    def test_a_provisioning_token_suppresses_both(self):
        self.assertFalse(self._fires(TOKEN_PATH, PRIVILEGED))
        self.assertFalse(self._fires(ISSUER_LOGIN, PRIVILEGED))
        self.assertFalse(self._fires(LOGIN, PRIVILEGED))

    def test_with_neither_credential_nothing_fires(self):
        # This is the state the plane was in. Both paths off, so the loud skip
        # is the only thing that speaks -- and it must not be reachable by a
        # path that silently succeeded.
        self.assertFalse(self._fires(TOKEN_PATH, NEITHER))
        self.assertFalse(self._fires(ISSUER_LOGIN, NEITHER))
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
