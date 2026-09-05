"""Behavioral contracts for the OpenBao-aware Ansible runner."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-ansible.sh"
MINTED_TOKEN = "test-runner-owned-token"
CALLER_TOKEN = "test-caller-owned-token"
APPROLE_SECRET = "test-approle-secret"


class RunAnsibleTokenContract(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.bin_path = self.temp_path / "bin"
        self.bin_path.mkdir()
        self.event_log = self.temp_path / "events.log"
        self.tmp_path = self.temp_path / "tmp"
        self.tmp_path.mkdir()
        # One fake for the OpenBao CLI. It also enforces the two contracts
        # the runner depends on and that no assertion below could otherwise
        # see: the secret_id arrives on stdin rather than in the argument
        # list, and each call asks for the single response field it uses.
        self._write_executable(
            "bao",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            auth=""
            if [[ ${{BAO_TOKEN:-}} == "$EXPECTED_MINTED_TOKEN" ]]; then
              auth=" runner-auth"
            fi
            for arg in "$@"; do
              if [[ $arg == *"$EXPECTED_APPROLE_SECRET"* ]]; then
                printf 'secret_id passed as an argument\n' >&2
                exit 64
              fi
            done
            case "$*" in
              *"auth/approle/login"*)
                [[ " $* " == *" -field=token "* ]] || exit 65
                [[ " $* " == *" secret_id=- "* ]] || exit 66
                piped=""
                IFS= read -r piped || true
                [[ $piped == "$EXPECTED_APPROLE_SECRET" ]] || exit 67
                printf 'bao write auth/approle/login\n' >> "$FAKE_EVENT_LOG"
                printf '%s\n' '{MINTED_TOKEN}'
                ;;
              *"sign/automation-ansible"*)
                [[ " $* " == *" -field=signed_key "* ]] || exit 68
                [[ " $* " == *" public_key=@"* ]] || exit 69
                printf 'bao write ssh-client-ca/sign/automation-ansible%s\n' \
                  "$auth" >> "$FAKE_EVENT_LOG"
                [[ ${{FAKE_SIGN_FAILURE:-0}} == 0 ]] || exit 2
                printf '%s\n' 'test-certificate'
                ;;
              *"token revoke -self"*)
                printf 'bao token revoke -self%s\n' "$auth" >> "$FAKE_EVENT_LOG"
                ;;
              *)
                exit 2
                ;;
            esac
            """,
        )
        self._write_executable(
            "ansible-playbook",
            """
            #!/usr/bin/env bash
            set -euo pipefail
            printf 'ansible\n' >> "$FAKE_EVENT_LOG"
            [[ ${BAO_TOKEN:-} == "$EXPECTED_CHILD_BAO_TOKEN" ]]
            printf 'child received expected token\n'
            """,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_executable(self, name: str, body: str):
        path = self.bin_path / name
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        path.chmod(0o700)

    def _run(self, caller_token=None, sign_failure=False):
        env = os.environ.copy()
        env.update(
            {
                "BAO_ADDR": "https://openbao.test",
                "OPENBAO_APPROLE_ANSIBLE_ROLE_ID": "test-role-id",
                "OPENBAO_APPROLE_ANSIBLE_SECRET_ID": APPROLE_SECRET,
                "EXPECTED_CHILD_BAO_TOKEN": caller_token or MINTED_TOKEN,
                "EXPECTED_MINTED_TOKEN": MINTED_TOKEN,
                "EXPECTED_APPROLE_SECRET": APPROLE_SECRET,
                "FAKE_EVENT_LOG": str(self.event_log),
                "FAKE_SIGN_FAILURE": "1" if sign_failure else "0",
                "PATH": f"{self.bin_path}{os.pathsep}{env['PATH']}",
                "TMPDIR": str(self.tmp_path),
            }
        )
        if caller_token is None:
            env.pop("BAO_TOKEN", None)
        else:
            env["BAO_TOKEN"] = caller_token

        return subprocess.run(
            [str(RUNNER), "playbooks/site.yml", "--limit", "localhost"],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    def _assert_no_secret_leak(self, result):
        output = result.stdout + result.stderr
        events = self.event_log.read_text(encoding="utf-8")
        for secret in (MINTED_TOKEN, CALLER_TOKEN, APPROLE_SECRET):
            self.assertNotIn(secret, output)
            self.assertNotIn(secret, events)

    def _assert_cert_cleanup(self):
        self.assertEqual(list(self.tmp_path.glob("ansible-sshcert.*")), [])

    def test_minted_token_reaches_child_then_is_revoked(self):
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.event_log.read_text(encoding="utf-8").splitlines(),
            [
                "bao write auth/approle/login",
                "bao write ssh-client-ca/sign/automation-ansible runner-auth",
                "ansible",
                "bao token revoke -self runner-auth",
            ],
        )
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


if __name__ == "__main__":
    unittest.main()
