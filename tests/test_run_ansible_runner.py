"""Behavioral contracts for the OpenBao-aware Ansible runner."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from run_ansible_runner_support import (
    CALLER_TOKEN,
    RUNNER,
    RunnerFixture,
)


class RunAnsibleTokenContract(RunnerFixture):
    def test_minted_token_reaches_child_then_is_revoked(self):
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login",
                "bao write ssh-client-ca/sign/automation-ansible runner-auth",
                "ansible",
                "child CONVERGE_ROLE_ID=test-role-id",
                "bao token revoke -self runner-auth",
            ],
        )
        self._assert_no_secret_leak(result)
        self._assert_cert_cleanup()

    def test_the_declared_identity_is_preferred_and_says_so(self):
        result = self._run(declared_identity=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("ansible-converge", output)
        # No warning: this is the bounded identity, which is the whole point.
        self.assertNotIn("UNDECLARED", output)
        self._assert_no_secret_leak(result)

    def test_falling_back_to_the_unbounded_identity_is_loud(self):
        # The bounded credential is not published everywhere yet, so the
        # fallback still has to work. What it must never do is happen quietly:
        # a silent fallback is how three days of converges ran on a credential
        # with no lifetime, no redemption cap and no source restriction, while
        # every recap stayed green.
        result = self._run(declared_identity=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        warning = result.stderr
        self.assertIn("UNDECLARED", result.stdout + warning)
        self.assertIn("WARNING", warning)
        self._assert_no_secret_leak(result)

    def test_semaphore_identity_is_preferred_over_declared_ansible_converge(self):
        # All three pairs present: the execution plane's own identity wins,
        # signs under its own CA role, and the ansible-converge warning path
        # is not even reached.
        result = self._run(declared_identity=True, semaphore_identity=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("authenticated as: semaphore", output)
        self.assertIn("(automation-semaphore)", output)
        self.assertNotIn("UNDECLARED", output)
        self.assertNotIn("ansible-converge", output)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login",
                "bao write ssh-client-ca/sign/automation-semaphore runner-auth",
                "ansible",
                "child CONVERGE_ROLE_ID=test-semaphore-role-id",
                "bao token revoke -self runner-auth",
            ],
        )
        self._assert_no_secret_leak(result)

    def test_semaphore_login_refused_falls_back_to_ansible_converge(self):
        # The semaphore AppRole's own source-address restriction can refuse a
        # caller (e.g. a workstation) even though its credential is present.
        # That is not a fatal mint failure: retry with the next identity in
        # order instead of aborting the converge.
        result = self._run(
            declared_identity=True,
            semaphore_identity=True,
            refuse_role_id="test-semaphore-role-id",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("AppRole login refused", result.stderr)
        self.assertIn("authenticated as: ansible-converge", output)
        self.assertNotIn("UNDECLARED", output)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login refused",
                "bao write auth/approle/login",
                "bao write ssh-client-ca/sign/automation-ansible runner-auth",
                "ansible",
                "child CONVERGE_ROLE_ID=test-declared-role-id",
                "bao token revoke -self runner-auth",
            ],
        )
        self._assert_no_secret_leak(result)
        self._assert_cert_cleanup()

    def test_node_converge_identity_wins_over_every_broader_pair(self):
        # It is inert and human-unlocked, so it is only in an environment
        # because an operator just unwrapped it for this run. Silently
        # preferring a broader pair that happens to be ambient on the same
        # workstation is the identity swap this ordering exists to prevent.
        result = self._run(
            declared_identity=True,
            semaphore_identity=True,
            node_converge_identity=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("authenticated as: openbao-node-converge", output)
        self.assertNotIn("UNDECLARED", output)
        self.assertIn("child CONVERGE_ROLE_ID=test-node-role-id", self.event_log.read_text(encoding="utf-8"))
        self._assert_no_secret_leak(result)

    def test_node_converge_login_refused_falls_through_instead_of_looping(self):
        # It shares automation-ansible with ansible-converge, so the retry loop
        # cannot tell the two apart by sign role. Without its own skip flag a
        # refused login re-selects the same tier forever.
        result = self._run(
            declared_identity=True,
            node_converge_identity=True,
            refuse_role_id="test-node-role-id",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("AppRole login refused", result.stderr)
        self.assertIn("authenticated as: ansible-converge", output)
        self._assert_no_secret_leak(result)
        self._assert_cert_cleanup()

    def test_caller_token_is_preserved_and_runner_token_revoked_before_child(self):
        result = self._run(caller_token=CALLER_TOKEN)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login",
                "bao write ssh-client-ca/sign/automation-ansible runner-auth",
                "bao token revoke -self runner-auth",
                "ansible",
                "child CONVERGE_ROLE_ID=test-role-id",
            ],
        )
        self._assert_no_secret_leak(result)
        self._assert_cert_cleanup()

    def test_sign_failure_is_loud_and_revokes_minted_token(self):
        result = self._run(sign_failure=True)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OpenBao SSH cert mint FAILED", result.stderr)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login",
                "bao write ssh-client-ca/sign/automation-ansible runner-auth",
                "bao token revoke -self runner-auth",
            ],
        )
        self._assert_no_secret_leak(result)
        self._assert_cert_cleanup()


class CheckoutFreshnessGuard(unittest.TestCase):
    """The guard must name the divergence it actually found.

    A checkout that is AHEAD of origin is zero commits behind it. Reporting
    that as "0 commit(s) behind -- refusing" reads as a broken guard rather
    than a fact about the checkout, and the obvious way to make a broken guard
    stop complaining is ALLOW_STALE_CHECKOUT=1 -- which converges unpushed,
    unreviewed local commits, the exact outcome the guard exists to prevent.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.upstream = root / "upstream"
        self.clone = root / "clone"
        self.env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
        }
        self._git("init", "-q", "-b", "main", str(self.upstream), cwd=root)
        (self.upstream / "seed").write_text("1\n", encoding="utf-8")
        self._git("add", "-A", cwd=self.upstream)
        self._git("commit", "-qm", "seed", cwd=self.upstream)
        self._git("clone", "-q", str(self.upstream), str(self.clone), cwd=root)
        scripts = self.clone / "scripts"
        scripts.mkdir(parents=True, exist_ok=True)
        (scripts / "run-ansible.sh").write_text(
            RUNNER.read_text(encoding="utf-8"), encoding="utf-8"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *args, cwd):
        subprocess.run(
            ["git", *args], cwd=str(cwd), env=self.env, check=True,
            capture_output=True,
        )

    def _run_guard(self):
        return subprocess.run(
            ["bash", "scripts/run-ansible.sh", "playbooks/site.yml"],
            cwd=str(self.clone), env=self.env, capture_output=True, text=True, check=False,
        )

    def test_ahead_checkout_is_named_as_ahead_and_says_to_push(self):
        (self.clone / "local-only").write_text("x\n", encoding="utf-8")
        self._git("add", "-A", cwd=self.clone)
        self._git("commit", "-qm", "local only", cwd=self.clone)

        result = self._run_guard()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1 ahead", result.stderr)
        self.assertIn("0 behind", result.stderr)
        self.assertIn("git push origin", result.stderr)
        # The stale-checkout remedy is wrong here and must not be suggested.
        self.assertNotIn("ALLOW_STALE_CHECKOUT", result.stderr)

    def test_behind_checkout_still_says_to_pull(self):
        (self.upstream / "newer").write_text("y\n", encoding="utf-8")
        self._git("add", "-A", cwd=self.upstream)
        self._git("commit", "-qm", "newer", cwd=self.upstream)

        result = self._run_guard()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("1 behind", result.stderr)
        self.assertIn("0 ahead", result.stderr)
        self.assertIn("--ff-only", result.stderr)


if __name__ == "__main__":
    unittest.main()
