"""Contract for the repo shim that configures the shared Ansible runner."""

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-ansible.sh"
MEDIA_URL = "https://media.example.test/servarr.git"
DEFAULTS = {
    "RUN_ANSIBLE_IDENTITIES": "openbao-node-converge?,signer?,semaphore?,ansible-converge?,ansible?",
    "RUN_ANSIBLE_SIGN_ROLE_OPENBAO_NODE_CONVERGE": "automation-ansible",
    "RUN_ANSIBLE_SIGN_ROLE_ANSIBLE_CONVERGE": "automation-ansible",
    "SSH_CERT_TTL": "2h",
    "RUN_ANSIBLE_RETIRING_IDENTITIES": "ansible",
    "RUN_ANSIBLE_WARN_NO_ISSUER": "1",
    "RUN_ANSIBLE_EXPORT_CONVERGE_IDENTITY": "1",
    "RUN_ANSIBLE_PIN_FILE": "servarr.pin",
    "RUN_ANSIBLE_PIN_DIR": "servarr",
    "RUN_ANSIBLE_PIN_URL": MEDIA_URL,
    "RUN_ANSIBLE_PIN_PLAYBOOKS": "05-media-and-gate.yml,site/05-media-and-gate.yml,playbooks/site/05-media-and-gate.yml",
    "RUN_ANSIBLE_PIN_OPTIONAL_PLAYBOOKS": "site.yml,playbooks/site.yml",
    "RUN_ANSIBLE_CHECKOUT_GUARD": "1",
    "RUN_ANSIBLE_MERGE_KNOWN_HOSTS": "1",
    "RUN_ANSIBLE_LIMIT_LOCALHOST": "1",
    "RUN_ANSIBLE_RECAP_CHECK": "1",
    "RUN_ANSIBLE_LOG_DIR": str(ROOT / ".ansible-run-logs"),
}
EXPORT_LINES = [
    'export RUN_ANSIBLE_IDENTITIES="${RUN_ANSIBLE_IDENTITIES:-openbao-node-converge?,signer?,semaphore?,ansible-converge?,ansible?}"',
    'export RUN_ANSIBLE_SIGN_ROLE_OPENBAO_NODE_CONVERGE="${RUN_ANSIBLE_SIGN_ROLE_OPENBAO_NODE_CONVERGE:-automation-ansible}"',
    'export RUN_ANSIBLE_SIGN_ROLE_ANSIBLE_CONVERGE="${RUN_ANSIBLE_SIGN_ROLE_ANSIBLE_CONVERGE:-automation-ansible}"',
    'export SSH_CERT_TTL="${SSH_CERT_TTL:-2h}"',
    'export RUN_ANSIBLE_RETIRING_IDENTITIES="${RUN_ANSIBLE_RETIRING_IDENTITIES:-ansible}"',
    'export RUN_ANSIBLE_WARN_NO_ISSUER="${RUN_ANSIBLE_WARN_NO_ISSUER:-1}"',
    'export RUN_ANSIBLE_EXPORT_CONVERGE_IDENTITY="${RUN_ANSIBLE_EXPORT_CONVERGE_IDENTITY:-1}"',
    'export RUN_ANSIBLE_PIN_FILE="${RUN_ANSIBLE_PIN_FILE:-servarr.pin}"',
    'export RUN_ANSIBLE_PIN_DIR="${RUN_ANSIBLE_PIN_DIR:-servarr}"',
    'export RUN_ANSIBLE_PIN_URL="${RUN_ANSIBLE_PIN_URL:-${MEDIA_STACK_REPO_URL:-}}"',
    'export RUN_ANSIBLE_PIN_PLAYBOOKS="${RUN_ANSIBLE_PIN_PLAYBOOKS:-05-media-and-gate.yml,site/05-media-and-gate.yml,playbooks/site/05-media-and-gate.yml}"',
    'export RUN_ANSIBLE_PIN_OPTIONAL_PLAYBOOKS="${RUN_ANSIBLE_PIN_OPTIONAL_PLAYBOOKS:-site.yml,playbooks/site.yml}"',
    'export RUN_ANSIBLE_CHECKOUT_GUARD="${RUN_ANSIBLE_CHECKOUT_GUARD:-1}"',
    'export RUN_ANSIBLE_MERGE_KNOWN_HOSTS="${RUN_ANSIBLE_MERGE_KNOWN_HOSTS:-1}"',
    'export RUN_ANSIBLE_LIMIT_LOCALHOST="${RUN_ANSIBLE_LIMIT_LOCALHOST:-1}"',
    'export RUN_ANSIBLE_RECAP_CHECK="${RUN_ANSIBLE_RECAP_CHECK:-1}"',
    'export RUN_ANSIBLE_LOG_DIR="${RUN_ANSIBLE_LOG_DIR:-$(git rev-parse --show-toplevel)/.ansible-run-logs}"',
]


class RunAnsibleShimContract(unittest.TestCase):
    def test_exact_defaults_and_shared_runner_exec(self):
        source = RUNNER.read_text(encoding="utf-8")
        self.assertIn(
            "# renovate: datasource=github-releases depName=dryvist/homelab-contracts",
            source,
        )
        operations = [
            line
            for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            operations,
            [
                "set -euo pipefail",
                *EXPORT_LINES,
                "HOMELAB_CONTRACTS_REF=v5.35.0",
                'exec nix run "github:dryvist/homelab-contracts/${HOMELAB_CONTRACTS_REF}#run-ansible" -- "$@"',
            ],
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            bin_path = temp_path / "bin"
            bin_path.mkdir()
            args_file = temp_path / "nix-args"
            env_file = temp_path / "runner-env"
            nix = bin_path / "nix"
            nix.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    printf '%s\\n' "$@" > "$RUNNER_TEST_ARGS_FILE"
                    {{
                      for name in {' '.join(DEFAULTS)}; do
                        value=$(printenv "$name")
                        printf '%s=%s\\n' "$name" "$value"
                      done
                    }} > "$RUNNER_TEST_ENV_FILE"
                    """
                ),
                encoding="utf-8",
            )
            nix.chmod(0o700)
            env = {
                "PATH": f"{bin_path}{os.pathsep}{os.environ.get('PATH', '')}",
                "RUNNER_TEST_ARGS_FILE": str(args_file),
                "RUNNER_TEST_ENV_FILE": str(env_file),
                "MEDIA_STACK_REPO_URL": MEDIA_URL,
            }
            result = subprocess.run(
                [str(RUNNER), "playbooks/site.yml", "--limit", "media_group"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            captured_args = args_file.read_text(encoding="utf-8").splitlines()
            captured_env = env_file.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            captured_args,
            [
                "run",
                "github:dryvist/homelab-contracts/v5.35.0#run-ansible",
                "--",
                "playbooks/site.yml",
                "--limit",
                "media_group",
            ],
        )
        self.assertEqual(
            dict(line.split("=", maxsplit=1) for line in captured_env),
            DEFAULTS,
        )


if __name__ == "__main__":
    unittest.main()
