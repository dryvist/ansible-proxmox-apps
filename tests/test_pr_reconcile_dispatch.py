"""The PR reconcile dispatch playbook mints per run, fires one request, and masks the token.

A Semaphore template in the dispatching repository calls
playbooks/pr-reconcile-dispatch.yml every 5 minutes while enabled, so the
playbook must read its inputs from the environment, mint a short-lived GitHub
token through the run's own OpenBao identity, and send exactly one
workflow_dispatch POST that accepts only a 204. These are plain YAML structure
checks in the style of the repository's other playbook tests.
"""

from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "playbooks/pr-reconcile-dispatch.yml"

REQUIRED_ENV = (
    "PR_RECONCILE_OWNER",
    "PR_RECONCILE_REPOSITORY",
    "PR_RECONCILE_WORKFLOW",
    "PR_RECONCILE_GITHUB_MOUNT",
    "PR_RECONCILE_PERMISSION_SET",
)

TOKEN_FACT = "pr_reconcile_github_token"

NON_MODULE_KEYS = {
    "name", "register", "changed_when", "no_log", "vars", "when", "tags",
    "loop", "loop_control", "block", "rescue", "always", "delegate_to",
    "become", "environment", "failed_when", "ignore_errors", "check_mode",
}


def _plays():
    return yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8"))


def _tasks(node):
    for task in node or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _tasks(task.get(key))


def _all_tasks():
    yield from _tasks(_plays()[0].get("tasks"))


def _fields(task):
    """Serialized task fields without block/rescue/always, for marker scans."""
    return str({k: v for k, v in task.items() if k not in {"block", "rescue", "always"}})


def _uses(task, needle):
    """Whether a module key on the task contains the needle (FQCN safe)."""
    return any(needle in key for key in task if key not in NON_MODULE_KEYS)


class EnvironmentContract(unittest.TestCase):
    def test_every_required_input_is_read_from_the_environment(self):
        text = PLAYBOOK.read_text(encoding="utf-8")
        for name in REQUIRED_ENV:
            with self.subTest(variable=name):
                self.assertIn(f"lookup('env', '{name}')", text)

    def test_the_ref_defaults_to_main(self):
        ref = _plays()[0]["vars"]["pr_reconcile_ref"]
        self.assertIn("lookup('env', 'PR_RECONCILE_REF')", ref)
        self.assertIn("default('main', true)", ref)

    def test_unset_inputs_fail_before_any_request(self):
        tasks = list(_all_tasks())
        named = next(t for t in tasks if t["name"] == "Name the unset dispatch inputs")
        gate = next(
            t for t in tasks if t["name"] == "Require every dispatch input before any request"
        )
        for name in REQUIRED_ENV + ("BAO_ADDR", "BAO_TOKEN/VAULT_TOKEN"):
            self.assertIn(name, _fields(named))
        self.assertIn(
            "pr_reconcile_missing_inputs | length == 0",
            gate["ansible.builtin.assert"]["that"],
        )
        first_request = next(i for i, t in enumerate(tasks) if _uses(t, "vault_write") or _uses(t, "uri"))
        self.assertLess(tasks.index(named), first_request)
        self.assertLess(tasks.index(gate), first_request)


class TokenMint(unittest.TestCase):
    def test_the_mint_follows_the_run_identity_pattern(self):
        mint = next(t for t in _all_tasks() if _uses(t, "vault_write"))
        call = mint["community.hashi_vault.vault_write"]
        self.assertEqual(call["auth_method"], "token")
        self.assertEqual(
            call["path"],
            "{{ pr_reconcile_github_mount }}/token/{{ pr_reconcile_permission_set }}",
        )
        self.assertEqual(call["url"], "{{ pr_reconcile_bao_addr }}")
        self.assertEqual(call["token"], "{{ pr_reconcile_bao_token }}")

    def test_the_run_identity_reads_bao_addr_and_bao_token(self):
        play_vars = _plays()[0]["vars"]
        self.assertEqual(play_vars["pr_reconcile_bao_addr"], "{{ lookup('env', 'BAO_ADDR') }}")
        token = play_vars["pr_reconcile_bao_token"]
        self.assertIn("lookup('env', 'BAO_TOKEN')", token)
        self.assertIn("default(lookup('env', 'VAULT_TOKEN'), true)", token)

    def test_the_minted_token_is_selected_and_required(self):
        tasks = list(_all_tasks())
        extract = next(t for t in tasks if t["name"] == "Read the minted GitHub token")
        self.assertIn(TOKEN_FACT, extract["ansible.builtin.set_fact"])
        require = next(t for t in tasks if t["name"] == "Require the minted GitHub token")
        self.assertIn(f"{TOKEN_FACT} | length > 0", require["ansible.builtin.assert"]["that"])


class TokenMasking(unittest.TestCase):
    def test_every_task_that_holds_a_token_is_masked(self):
        markers = (TOKEN_FACT, "pr_reconcile_mint", "pr_reconcile_bao_token", "Authorization")
        masked = []
        for task in _all_tasks():
            if any(marker in _fields(task) for marker in markers):
                self.assertTrue(task.get("no_log"), task["name"])
                masked.append(task["name"])
        self.assertGreaterEqual(len(masked), 4)

    def test_the_token_only_travels_in_the_authorization_header(self):
        dispatch = next(t for t in _all_tasks() if _uses(t, "uri"))
        call = dispatch["ansible.builtin.uri"]
        self.assertIn(TOKEN_FACT, call["headers"]["Authorization"])
        self.assertNotIn(TOKEN_FACT, call["url"])
        self.assertEqual(call["follow_redirects"], "none")
        self.assertEqual(call["unredirected_headers"], ["Authorization"])


class DispatchRequest(unittest.TestCase):
    def test_exactly_one_uri_request_accepts_only_a_204(self):
        requests = [t["ansible.builtin.uri"] for t in _all_tasks() if _uses(t, "uri")]
        self.assertEqual(len(requests), 1)
        call = requests[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["status_code"], 204)
        self.assertEqual(call["timeout"], 30)
        self.assertEqual(call["body"], {"ref": "{{ pr_reconcile_ref }}"})
        self.assertIn("/actions/workflows/{{ pr_reconcile_workflow }}/dispatches", call["url"])

    def test_the_run_writes_no_state_and_reports_no_change(self):
        module_keys = {
            key for task in _all_tasks() for key in task if key not in NON_MODULE_KEYS
        }
        self.assertEqual(
            module_keys,
            {
                "ansible.builtin.set_fact",
                "ansible.builtin.assert",
                "community.hashi_vault.vault_write",
                "ansible.builtin.uri",
            },
        )
        for task in _all_tasks():
            if _uses(task, "vault_write") or _uses(task, "uri"):
                self.assertIs(task["changed_when"], False, task["name"])

    def test_no_shell_or_command_module_anywhere(self):
        forbidden = {"shell", "command", "ansible.builtin.shell", "ansible.builtin.command"}
        for task in _all_tasks():
            for key in task:
                self.assertNotIn(key, forbidden, task["name"])


if __name__ == "__main__":
    unittest.main()
