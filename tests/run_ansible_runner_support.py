"""Shared sandbox for the run-ansible.sh identity tests: a fake store CLI and
a fake ansible-playbook on PATH, plus the env each test starts from."""

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-ansible.sh"
MINTED_TOKEN = "test-runner-owned-token"
CALLER_TOKEN = "test-caller-owned-token"
APPROLE_SECRET = "test-approle-secret"
GENERIC_ENV = {
    "SECRET_STORE_ADDR": "https://store.test",
    "SSH_SIGNER_ROLE_ID": "test-signer-role-id",
    "SSH_SIGNER_SECRET_ID": APPROLE_SECRET,
    "SSH_CA_MOUNT": "test-mount",
    "SSH_SIGNER_ROLE": "test-sign-role",
}


class RunnerFixture(unittest.TestCase):
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
            if [[ -n ${{EXPECTED_BAO_ADDR:-}} && ${{BAO_ADDR:-}} != "$EXPECTED_BAO_ADDR" ]]; then
              exit 71
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
                if [[ -n "${{FAKE_REFUSE_ROLE_ID:-}}" && " $* " == *" role_id=$FAKE_REFUSE_ROLE_ID "* ]]; then
                  printf 'bao write auth/approle/login refused\n' >> "$FAKE_EVENT_LOG"
                  exit 70
                fi
                printf 'bao write auth/approle/login\n' >> "$FAKE_EVENT_LOG"
                printf '%s\n' '{MINTED_TOKEN}'
                ;;
              *"/sign/"*)
                [[ " $* " == *" -field=signed_key "* ]] || exit 68
                [[ " $* " == *" public_key=@"* ]] || exit 69
                sign_path=$(printf '%s' "$*" | grep -o '[a-z-]*/sign/[a-z-]*')
                printf 'bao write %s%s\n' \
                  "$sign_path" "$auth" >> "$FAKE_EVENT_LOG"
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
            printf 'child CONVERGE_ROLE_ID=%s\n' "${CONVERGE_ROLE_ID:-}" >> "$FAKE_EVENT_LOG"
            printf 'child received expected token\n'
            """,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_executable(self, name: str, body: str):
        path = self.bin_path / name
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        path.chmod(0o700)

    def _run(
        self,
        caller_token=None,
        sign_failure=False,
        declared_identity=False,
        semaphore_identity=False,
        node_converge_identity=False,
        refuse_role_id=None,
        extra_env=None,
        legacy=True,
    ):
        env = {k: v for k, v in os.environ.items() if k not in GENERIC_ENV}
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
                "FAKE_REFUSE_ROLE_ID": refuse_role_id or "",
                "PATH": f"{self.bin_path}{os.pathsep}{env['PATH']}",
                "TMPDIR": str(self.tmp_path),
            }
        )
        # Two AppRoles carry an identical grant: one declared and bounded, one
        # declared nowhere and bounded on no axis. The runner must prefer the
        # first and say so loudly when it falls back to the second.
        env.pop("OPENBAO_APPROLE_ANSIBLE_CONVERGE_ROLE_ID", None)
        env.pop("OPENBAO_APPROLE_ANSIBLE_CONVERGE_SECRET_ID", None)
        if declared_identity:
            env["OPENBAO_APPROLE_ANSIBLE_CONVERGE_ROLE_ID"] = "test-declared-role-id"
            env["OPENBAO_APPROLE_ANSIBLE_CONVERGE_SECRET_ID"] = APPROLE_SECRET
        env.pop("OPENBAO_APPROLE_SEMAPHORE_ROLE_ID", None)
        env.pop("OPENBAO_APPROLE_SEMAPHORE_SECRET_ID", None)
        if semaphore_identity:
            env["OPENBAO_APPROLE_SEMAPHORE_ROLE_ID"] = "test-semaphore-role-id"
            env["OPENBAO_APPROLE_SEMAPHORE_SECRET_ID"] = APPROLE_SECRET
        env.pop("OPENBAO_APPROLE_OPENBAO_NODE_CONVERGE_ROLE_ID", None)
        env.pop("OPENBAO_APPROLE_OPENBAO_NODE_CONVERGE_SECRET_ID", None)
        if node_converge_identity:
            env["OPENBAO_APPROLE_OPENBAO_NODE_CONVERGE_ROLE_ID"] = "test-node-role-id"
            env["OPENBAO_APPROLE_OPENBAO_NODE_CONVERGE_SECRET_ID"] = APPROLE_SECRET
        if not legacy:
            for name in ("BAO_ADDR", "OPENBAO_APPROLE_ANSIBLE_ROLE_ID", "OPENBAO_APPROLE_ANSIBLE_SECRET_ID"):
                env.pop(name, None)
        env.update(extra_env or {})
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
