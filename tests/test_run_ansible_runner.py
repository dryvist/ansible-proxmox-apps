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
        self._write_executable(
            "jq",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            filter=""
            for arg in "$@"; do
              filter=$arg
            done
            case "$filter" in
              .auth.client_token)
                cat >/dev/null
                printf '%s\\n' '{MINTED_TOKEN}'
                ;;
              .data.signed_key)
                cat >/dev/null
                printf '%s\\n' 'test-certificate'
                ;;
              *)
                printf '%s\\n' '{{}}'
                ;;
            esac
            """,
        )
        self._write_executable(
            "curl",
            f"""
            #!/usr/bin/env bash
            set -euo pipefail
            url="" header_arg="" next_is_header=false
            for arg in "$@"; do
              if $next_is_header; then
                header_arg=$arg
                next_is_header=false
                continue
              fi
              case "$arg" in
                -H|--header) next_is_header=true ;;
                http://*|https://*) url=$arg ;;
              esac
            done
            auth=""
            if [[ $header_arg == @/dev/fd/* ]]; then
              IFS= read -r auth_header < "${{header_arg#@}}"
              [[ $auth_header == "X-Vault-Token: $EXPECTED_MINTED_TOKEN" ]]
              auth=" runner-auth"
            fi
            printf 'curl %s%s\n' "$url" "$auth" >> "$FAKE_EVENT_LOG"
            case "$url" in
              */auth/approle/login)
                cat >/dev/null
                printf '%s\n' '{{"auth":{{"client_token":"{MINTED_TOKEN}"}}}}'
                ;;
              */sign/automation-ansible)
                cat >/dev/null
                [[ ${{FAKE_SIGN_FAILURE:-0}} == 0 ]] || exit 22
                printf '%s\n' '{{"data":{{"signed_key":"test-certificate"}}}}'
                ;;
              */auth/token/revoke-self)
                cat >/dev/null
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
                "curl https://openbao.test/v1/auth/approle/login",
                "curl https://openbao.test/v1/ssh-client-ca/sign/automation-ansible runner-auth",
                "ansible",
                "curl https://openbao.test/v1/auth/token/revoke-self runner-auth",
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
                "curl https://openbao.test/v1/auth/approle/login",
                "curl https://openbao.test/v1/ssh-client-ca/sign/automation-ansible runner-auth",
                "curl https://openbao.test/v1/auth/token/revoke-self runner-auth",
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
                "curl https://openbao.test/v1/auth/approle/login",
                "curl https://openbao.test/v1/ssh-client-ca/sign/automation-ansible runner-auth",
                "curl https://openbao.test/v1/auth/token/revoke-self runner-auth",
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
            cwd=str(self.clone), env=self.env, capture_output=True, text=True,
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
