"""Generic signer env names in run-ansible.sh: read before every legacy tier
except node-converge, refused without a mount or signing role, and a refused
login on the last tier stops instead of looping."""

import unittest

from run_ansible_runner_support import GENERIC_ENV, RunnerFixture


class SignerEnvContract(RunnerFixture):

    def test_generic_names_alone_sign_with_supplied_store_mount_and_role(self):
        result = self._run(
            extra_env={**GENERIC_ENV, "EXPECTED_BAO_ADDR": "https://store.test"},
            legacy=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("authenticated as: signer", result.stdout)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login",
                "bao write test-mount/sign/test-sign-role runner-auth",
                "ansible",
                "child CONVERGE_ROLE_ID=test-signer-role-id",
                "bao token revoke -self runner-auth",
            ],
        )
        self._assert_no_secret_leak(result)
        self._assert_cert_cleanup()

    def test_generic_names_win_over_legacy_tiers_below_node_converge(self):
        result = self._run(
            declared_identity=True,
            semaphore_identity=True,
            extra_env={**GENERIC_ENV, "EXPECTED_BAO_ADDR": "https://store.test"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("authenticated as: signer", result.stdout)
        events = self.event_log.read_text(encoding="utf-8")
        self.assertIn("bao write test-mount/sign/test-sign-role runner-auth", events)
        self.assertNotIn("automation-", events)
        self._assert_no_secret_leak(result)

    def test_node_converge_still_wins_over_generic_names(self):
        result = self._run(node_converge_identity=True, extra_env=GENERIC_ENV)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("authenticated as: openbao-node-converge", result.stdout)
        self.assertIn("child CONVERGE_ROLE_ID=test-node-role-id", self.event_log.read_text(encoding="utf-8"))

    def test_generic_login_refused_falls_through_to_legacy_tier(self):
        result = self._run(
            semaphore_identity=True,
            extra_env={**GENERIC_ENV, "SSH_SIGNER_ROLE": "automation-semaphore"},
            refuse_role_id="test-signer-role-id",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AppRole login refused for identity: signer", result.stderr)
        self.assertIn("authenticated as: semaphore", result.stdout)
        self._assert_no_secret_leak(result)

    def test_generic_names_without_mount_refuse(self):
        env = dict(GENERIC_ENV)
        del env["SSH_CA_MOUNT"]
        result = self._run(extra_env=env, legacy=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SSH_CA_MOUNT or SSH_SIGNER_ROLE is not", result.stderr)
        self.assertFalse(self.event_log.exists())

    def test_last_tier_login_refused_stops_instead_of_looping(self):
        result = self._run(refuse_role_id="test-role-id")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no identity left to try", result.stderr)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            ["bao write auth/approle/login refused"],
        )


if __name__ == "__main__":
    unittest.main()
