"""Regression for the reconcile-mode mount/auth gate in roles/openbao/tasks/init.yml.

Measured live: `bao secrets list` (sys/mounts) 403s under the openbao-reconcile
identity, exactly like `bao auth list` (sys/auth) already does for 09. Before
this fix, init.yml did not gate the "Enable the KV mounts and seed per-app
service secrets" include (03-kv-mounts-and-seed-secrets.yml) the way it gates
04/05/06/07/09 -- so that file's own hard-fail-on-denied-read task aborted the
rest of init.yml under every workstation reconcile converge, including the
AppRole/CIDR reconcile task (10-approles.yml) that runs after it. This asserts
03's include carries the same reconcile-mode skip as its sibling 09, so a
future edit cannot silently drop it again.
"""

from pathlib import Path
import unittest

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "roles" / "openbao" / "tasks" / "init.yml"

KV_MOUNTS_STEP = "Enable the KV mounts and seed per-app service secrets"
AUTH_METHODS_STEP = "Enable AppRole/JWT auth and reconcile Terrakube workspace JWT roles"


def _steps(node):
    if isinstance(node, list):
        for entry in node:
            yield from _steps(entry)
    elif isinstance(node, dict):
        if "name" in node:
            yield node
        for key in ("block", "rescue", "always"):
            if key in node:
                yield from _steps(node[key])


class ReconcileModeMountGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.steps = {s["name"]: s for s in _steps(yaml.safe_load(INIT.read_text()))}
        for name in (KV_MOUNTS_STEP, AUTH_METHODS_STEP):
            assert name in cls.steps, f"{name!r} not found in {INIT}"
        cls.env = Environment()

    def _fires_under_reconcile(self, step_name):
        cond = self.steps[step_name].get("when")
        if cond is None:
            return True
        conds = [cond] if isinstance(cond, str) else cond
        for c in conds:
            rendered = self.env.from_string("{{ %s }}" % c).render(
                openbao_reconcile_mode=True
            )
            if rendered.strip() != "True":
                return False
        return True

    def test_kv_mounts_step_is_skipped_under_reconcile_mode(self):
        self.assertFalse(self._fires_under_reconcile(KV_MOUNTS_STEP))

    def test_auth_methods_step_stays_skipped_under_reconcile_mode(self):
        # The sibling this fix was modeled on -- pinned so both can't drift
        # back out of sync with each other.
        self.assertFalse(self._fires_under_reconcile(AUTH_METHODS_STEP))


if __name__ == "__main__":
    unittest.main()
