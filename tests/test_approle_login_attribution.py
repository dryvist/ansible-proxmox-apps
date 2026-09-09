#!/usr/bin/env python3
"""The AppRole bounds validator must attribute a refused login to its identity.

The play logs in as every identity whose credentials are ambient. Those logins
run under `no_log`, because the command's arguments carry a role_id and its
result carries an issued token. When a login was allowed to fail the task, the
play aborted with a censored message naming nothing -- so a run that could
speak for two identities reported only that "an item failed", which is the one
outcome an operator cannot act on.

These are structural assertions against the play itself. They fail if the
attribution is removed, if a refused login is allowed to abort the run again,
if a failed login's result is fed to the token lookup, or if anything wider
than the projected fields is carried out of the no_log boundary.
"""

import unittest
from pathlib import Path

import yaml

PLAY = Path(__file__).resolve().parent.parent / "playbooks" / "verify-approle-ttls.yml"

LOGIN = "Log in with each reachable AppRole"
ATTRIBUTE = "Attribute every login outcome to its identity"
LOOKUP = "Look up each issued token"
REVOKE = "Revoke every token this play created"
FINAL = "Every reachable identity authenticates"

# Everything the attribution step is allowed to carry past `no_log`. `stdout`
# is the issued token and `secret_id` is the credential itself; neither may
# appear, and a new key here is a deliberate decision, not an accident.
ALLOWED_PROJECTED_KEYS = {"name", "rc", "reason"}


def _tasks(node):
    """Every task mapping in the play, including block/rescue/always bodies."""
    if isinstance(node, list):
        for entry in node:
            yield from _tasks(entry)
    elif isinstance(node, dict):
        if "name" in node and not {"hosts", "tasks"} <= set(node):
            yield node
        for key in ("tasks", "block", "rescue", "always", "pre_tasks", "post_tasks"):
            if key in node:
                yield from _tasks(node[key])


class ApproleLoginAttribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(PLAY.read_text())
        cls.tasks = {t["name"]: t for t in _tasks(cls.doc)}
        # Guards the guard: every name below must exist, or each assertion
        # further down would pass by looking up nothing.
        for name in (LOGIN, ATTRIBUTE, LOOKUP, REVOKE, FINAL):
            assert name in cls.tasks, f"{name!r} not found in {PLAY}"

    def test_a_refused_login_does_not_abort_the_run(self):
        login = self.tasks[LOGIN]
        self.assertEqual(login.get("failed_when"), False)
        self.assertTrue(login.get("no_log"), "the login result carries a token")

    def test_the_attribution_projects_only_safe_fields(self):
        body = self.tasks[ATTRIBUTE]["ansible.builtin.set_fact"]["_login_outcomes"]
        # The expression is a Jinja string; read the keys it builds out of it.
        keys = {
            line.split("'")[1]
            for line in body.splitlines()
            if line.strip().startswith("'")
        }
        self.assertEqual(keys, ALLOWED_PROJECTED_KEYS)
        self.assertNotIn("secret_id", body)
        self.assertNotIn("item.stdout", body)
        self.assertTrue(self.tasks[ATTRIBUTE].get("no_log"))

    def test_only_successful_logins_reach_the_token_tasks(self):
        for name in (LOOKUP, REVOKE):
            loop = self.tasks[name]["loop"]
            self.assertIn("'rc', 'equalto', 0", loop,
                          f"{name} would use a failed login's empty stdout")

    def test_the_login_assertion_runs_last(self):
        # A dead credential and an unbounded token are separate findings.
        # Asserting the login earlier aborts before the bounds are measured,
        # so one broken identity would hide the state of every working one.
        ordered = [t["name"] for t in _tasks(self.doc)]
        self.assertEqual(ordered[-1], FINAL)
        self.assertLess(ordered.index(LOOKUP), ordered.index(FINAL))


if __name__ == "__main__":
    unittest.main()
